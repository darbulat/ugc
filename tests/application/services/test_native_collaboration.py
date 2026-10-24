"""Native collaboration orchestration using the transactional memory adapter."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from tests.application.services.test_collaboration_service import (
    setup_lifecycle,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


def setup(platform="telegram"):
    service, repo, scope, clock, Command, stranger = setup_lifecycle()
    command = Command(
        assignment_id=scope.assignment_id,
        actor_id=scope.client_id,
        action="assign",
        operation_key="native",
        expected_version=0,
        due_at=clock.at + timedelta(days=2),
        terms_reference="synthetic terms",
    )
    return (
        service,
        repo,
        scope,
        command,
        AuthenticatedMessengerPrincipal(scope.client_id, platform, "123"),
        stranger,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_current_native_scope_succeeds(platform):
    service, repo, scope, command, principal, _ = setup(platform)
    repo.actors[scope.client_id] = replace(
        repo.actors[scope.client_id], telegram_id="123", max_id="123"
    )
    async with repo.transaction() as session:
        record, current, actions = await service.execute_authenticated(
            command, principal, session=session
        )
        assert current and "start" in actions
        assert await service.get_authenticated(
            scope.assignment_id, principal, session=session
        ) == (record, current, actions)
    assert len(repo.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_changed_binding_denies_status_command_and_replay(platform):
    service, repo, scope, command, principal, _ = setup(platform)
    for method, value in (
        ("get_authenticated", scope.assignment_id),
        ("execute_authenticated", command),
    ):
        async with repo.transaction() as session:
            with pytest.raises(ValueError, match="financial_principal_changed"):
                await getattr(service, method)(
                    value, principal, session=session
                )
    assert not repo.records and not repo.events and not repo.outbox


@pytest.mark.asyncio
async def test_work_missing_assignment_checks_actor_then_returns_absent():
    service, repo, _, _, principal, _ = setup()
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await service.get_authenticated(uuid4(), principal, session=session)
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    async with repo.transaction() as session:
        assert (
            await service.get_authenticated(uuid4(), principal, session=session)
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["item", "order", "swap", "party"])
async def test_work_same_users_changed_source_tuple_refuses(change):
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )

    async def changed_users(user_ids, *, session):
        updates = {
            "item": {"paid_item_id": uuid4()},
            "order": {"order_id": uuid4()},
            "swap": {
                "creator_id": scope.manager_id,
                "manager_id": scope.creator_id,
            },
            "party": {"creator_id": uuid4()},
        }
        repo.scopes[scope.assignment_id] = replace(scope, **updates[change])
        return {uid: repo.actors.get(uid) for uid in user_ids}

    repo._lock_principal_users = changed_users
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="collaboration_scope_changed"):
            await service.execute_authenticated(
                command, principal, session=session
            )
    assert not repo.events and not repo.outbox


@pytest.mark.asyncio
@pytest.mark.parametrize("manager", [False, True])
@pytest.mark.parametrize("actor_first", [False, True])
async def test_work_complete_sorted_user_scope_precedes_item(
    manager, actor_first
):
    service, repo, scope, command, principal, stranger = setup()
    if not manager:
        scope = replace(scope, manager_id=None)
        repo.scopes[scope.assignment_id] = scope
    old_stranger = repo.actors.pop(stranger)
    stranger = UUID(int=1 if actor_first else 2**128 - 1)
    repo.actors[stranger] = replace(old_stranger, user_id=stranger)
    principal = replace(principal, user_id=stranger)
    repo.actors[stranger] = replace(repo.actors[stranger], telegram_id="123")
    steps = []
    original = repo.lock_scope

    async def users(ids, *, session):
        steps.append(("users", ids))
        return {uid: repo.actors.get(uid) for uid in ids}

    async def item(assignment, *, session, expected_scope=None):
        steps.append(("item", expected_scope.paid_item_id))
        return await original(
            assignment, session=session, expected_scope=expected_scope
        )

    repo._lock_principal_users, repo.lock_scope = users, item
    async with repo.transaction() as session:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_authenticated(
                scope.assignment_id, principal, session=session
            )
    expected = {scope.client_id, scope.creator_id, stranger}
    if manager:
        expected.add(scope.manager_id)
    assert steps[0] == ("users", tuple(sorted(expected)))
    assert steps[1:] == [("item", scope.paid_item_id)] * 2


@pytest.mark.asyncio
async def test_work_capabilities_reuse_prepared_transaction():
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    calls = []
    original = repo.prepare_principal_scope

    async def prepare(*args, **kwargs):
        calls.append("prepare")
        return await original(*args, **kwargs)

    repo.prepare_principal_scope = prepare
    async with repo.transaction() as session:
        await service.execute_authenticated(command, principal, session=session)
    assert calls == ["prepare"]


@pytest.mark.asyncio
async def test_work_reentrant_scope_never_locks_a_changed_item():
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    original = repo.get_command
    prepared_items = []
    original_scope = repo.lock_scope

    async def scope_call(assignment_id, *, session, expected_scope=None):
        prepared_items.append(expected_scope.paid_item_id)
        return await original_scope(
            assignment_id, session=session, expected_scope=expected_scope
        )

    async def changed(*args, **kwargs):
        repo.scopes[scope.assignment_id] = replace(scope, paid_item_id=uuid4())
        return await original(*args, **kwargs)

    repo.get_command, repo.lock_scope = changed, scope_call
    with pytest.raises(ValueError, match="collaboration_scope_changed"):
        async with repo.transaction() as session:
            await service.execute_authenticated(
                command, principal, session=session
            )
    assert prepared_items == [scope.paid_item_id] * 3
    assert not repo.events and not repo.outbox


@pytest.mark.asyncio
async def test_work_scope_is_not_a_session_lifetime_capability():
    _, repo, scope, _, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    async with repo.transaction() as session:
        prepared = await repo.prepare_principal_scope(
            scope.assignment_id, principal.user_id, principal, session=session
        )
    with pytest.raises(ValueError, match="caller_transaction_required"):
        await repo.lock_scope(
            scope.assignment_id, session=session, expected_scope=prepared
        )
    async with repo.transaction() as other:
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.lock_scope(
                scope.assignment_id, session=other, expected_scope=prepared
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("binding", [None, "changed"])
async def test_work_changed_binding_denies_existing_receipt(platform, binding):
    service, repo, scope, command, principal, _ = setup(platform)
    actor = replace(
        repo.actors[principal.user_id], telegram_id="123", max_id="123"
    )
    repo.actors[principal.user_id] = actor
    async with repo.transaction() as session:
        await service.execute_authenticated(command, principal, session=session)
    before = (
        dict(repo.events),
        dict(repo.outbox),
        dict(repo.notices),
        dict(repo.records),
    )
    repo.actors[principal.user_id] = replace(
        actor, **{f"{platform}_id": binding}
    )
    with pytest.raises(ValueError, match="financial_principal_changed"):
        async with repo.transaction() as session:
            await service.execute_authenticated(
                command, principal, session=session
            )
    assert (repo.events, repo.outbox, repo.notices, repo.records) == before


@pytest.mark.asyncio
async def test_work_same_owner_cross_platform_replay_keeps_economic_receipt():
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123", max_id="456"
    )
    async with repo.transaction() as session:
        first = await service.execute_authenticated(
            command, principal, session=session
        )
    async with repo.transaction() as session:
        second = await service.execute_authenticated(
            command,
            replace(principal, platform="max", external_id="456"),
            session=session,
        )
    assert first == second and len(repo.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ({"status": "blocked"}, "active_actor_required"),
        ({"is_client": False}, "client_consent_required"),
    ],
)
async def test_work_current_role_status_still_deny(change, code):
    service, repo, _, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123", **change
    )
    with pytest.raises(PermissionError, match=code):
        async with repo.transaction() as session:
            await service.execute_authenticated(
                command, principal, session=session
            )
    assert not repo.events


@pytest.mark.asyncio
async def test_work_missing_assignment_never_falls_through_to_new_scope():
    service, repo, scope, _, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    repo.scopes.clear()
    original = repo._lock_principal_users

    async def appeared(ids, *, session):
        repo.scopes[scope.assignment_id] = scope
        return await original(ids, session=session)

    repo._lock_principal_users = appeared
    async with repo.transaction() as session:
        assert (
            await service.get_authenticated(
                scope.assignment_id, principal, session=session
            )
            is None
        )
    assert not repo.events


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "execute"])
@pytest.mark.parametrize("proof", [None, "uuid", "other"])
async def test_work_public_orchestration_requires_its_actor_proof(
    method, proof
):
    service, repo, scope, command, principal, stranger = setup()
    principal = (
        None
        if proof is None
        else uuid4()
        if proof == "uuid"
        else replace(principal, user_id=stranger)
    )
    with pytest.raises(
        (ValueError, PermissionError),
        match="financial_principal_changed|collaboration_view_forbidden",
    ):
        async with repo.transaction() as session:
            if method == "get":
                await service.get_authenticated(
                    scope.assignment_id, principal, session=session
                )
            else:
                await service.execute_authenticated(
                    command, principal, session=session
                )
    assert not repo.events


@pytest.mark.asyncio
async def test_work_absent_record_and_assignment_have_distinct_public_results():
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    async with repo.transaction() as session:
        assert (
            await service.get_authenticated(
                scope.assignment_id, principal, session=session
            )
            is None
        )
    repo.scopes.clear()
    with pytest.raises(ValueError, match="assignment_not_found"):
        async with repo.transaction() as session:
            await service.execute_authenticated(
                command, principal, session=session
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["commit", "rollback"])
async def test_sql_prepared_scope_rejects_finished_root_before_sql(
    finish, monkeypatch
):
    """Unconnected real AsyncSession tests lifetime rejection only, no SQL."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from ugc_bot.application.collaboration_ports import (
        CollaborationPrincipalScope,
    )
    from ugc_bot.infrastructure.db.repositories.collaborations import (
        SqlAlchemyCollaborationRepository,
    )

    _, _, scope, _, principal, _ = setup()
    reads = []

    async def forbidden(*args, **kwargs):
        reads.append("SQL")
        raise AssertionError("lifetime guard must precede SQL")

    async with AsyncSession() as session:
        await session.begin()
        prepared = CollaborationPrincipalScope(
            assignment_id=scope.assignment_id,
            paid_item_id=scope.paid_item_id,
            order_id=scope.order_id,
            client_id=scope.client_id,
            creator_id=scope.creator_id,
            manager_id=scope.manager_id,
            actor_id=principal.user_id,
            user_ids=tuple(
                sorted({scope.client_id, scope.creator_id, scope.manager_id})
            ),
            owner_session=session,
            root_transaction=session.sync_session.get_transaction(),
        )
        await getattr(session, finish)()
        monkeypatch.setattr(session, "execute", forbidden)
        monkeypatch.setattr(session, "scalar", forbidden)
        repo = SqlAlchemyCollaborationRepository()
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.lock_scope(
                scope.assignment_id, session=session, expected_scope=prepared
            )
        await session.begin()
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.lock_scope(
                scope.assignment_id, session=session, expected_scope=prepared
            )
        async with AsyncSession() as other:
            await other.begin()
            monkeypatch.setattr(other, "execute", forbidden)
            monkeypatch.setattr(other, "scalar", forbidden)
            with pytest.raises(ValueError, match="caller_transaction_required"):
                await repo.lock_scope(
                    scope.assignment_id, session=other, expected_scope=prepared
                )
    assert reads == []


@pytest.mark.asyncio
async def test_work_current_manager_membership_required_on_public_paths():
    service, repo, scope, _, principal, _ = setup()
    principal = replace(principal, user_id=scope.manager_id)
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123", manager_order_ids=()
    )
    with pytest.raises(PermissionError, match="collaboration_view_forbidden"):
        async with repo.transaction() as session:
            await service.get_authenticated(
                scope.assignment_id, principal, session=session
            )
    assert not repo.events


@pytest.mark.asyncio
async def test_work_system_notice_and_sweep_keep_existing_contract():
    from tests.application.services.test_collaboration_notice_delivery import (
        setup_delivery,
    )
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )
    from ugc_bot.domain.collaboration import CollaborationState

    worker, _, repo, scope, clock, _, _, transport = await setup_delivery()

    async def forbidden(*args, **kwargs):
        raise AssertionError("trusted system must never prepare public Users")

    repo.prepare_principal_scope = forbidden
    repo._lock_principal_users = forbidden
    await worker.run_once()
    assert len(transport.sent) == 1
    notice = repo.records[scope.assignment_id].collaboration
    assert notice.notice_delivered_at == clock.at
    clock.at += timedelta(hours=72)
    result = await CollaborationSweepService(worker.lifecycle, repo).run_once()
    assert result.changed == 1 and result.rejected == 0
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == CollaborationState.SUCCESS_FINAL
    )


@pytest.mark.asyncio
async def test_sql_preparation_inside_savepoint_refuses_before_sql(monkeypatch):
    """An unconnected savepoint cannot grant proof beyond its rollback."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from ugc_bot.infrastructure.db.repositories.collaborations import (
        SqlAlchemyCollaborationRepository,
    )

    _, _, scope, _, principal, _ = setup()
    reads = []

    async def forbidden(*args, **kwargs):
        reads.append("SQL")
        raise AssertionError("savepoint guard must precede SQL")

    async with AsyncSession() as session:
        await session.begin()
        async with session.begin_nested():
            monkeypatch.setattr(session, "execute", forbidden)
            monkeypatch.setattr(session, "scalar", forbidden)
            with pytest.raises(ValueError, match="caller_transaction_required"):
                await (
                    SqlAlchemyCollaborationRepository().prepare_principal_scope(
                        scope.assignment_id,
                        principal.user_id,
                        principal,
                        session=session,
                    )
                )
    assert reads == []


@pytest.mark.asyncio
async def test_work_missing_prospective_user_refuses_without_persisting():
    service, repo, scope, command, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    repo.actors.pop(scope.manager_id)
    with pytest.raises(ValueError, match="collaboration_scope_changed"):
        async with repo.transaction() as session:
            await service.execute_authenticated(
                command, principal, session=session
            )
    assert not repo.events and not repo.outbox


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, "uuid"])
async def test_work_preparation_itself_requires_typed_proof(proof):
    _, repo, scope, _, principal, _ = setup()
    repo.actors[principal.user_id] = replace(
        repo.actors[principal.user_id], telegram_id="123"
    )
    with pytest.raises(ValueError, match="financial_principal_changed"):
        async with repo.transaction() as session:
            await repo.prepare_principal_scope(
                scope.assignment_id,
                principal.user_id,
                None if proof is None else principal.user_id,
                session=session,
            )
