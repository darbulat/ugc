"""Normal signed intake/work calls under actual PostgreSQL native barriers."""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from tests.helpers.native_caller_pg import (
    NativeCallerCase,
    assert_user_item_order,
    backend_pid,
    blocked_by,
    finish,
    observe_sql,
)
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_pg,
)
from tests.postgres_financial.test_order_intake import (
    command as intake_command,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as intake_env,
)
from tests.postgres_financial.test_v1_capture import capture_env as capture_env
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    ManagerOrderModel,
    UserModel,
)

__all__ = ["intake_env", "collaboration_pg", "capture_env"]


@pytest.fixture(scope="session")
def native_caller_evidence():
    records = []
    yield records
    path = os.environ.get("NATIVE_CALLER_EVIDENCE_PATH")
    if path:
        Path(path).write_text(json.dumps(records, indent=2, default=str) + "\n")


@pytest_asyncio.fixture
async def native_intake(intake_env):
    env = intake_env
    command = intake_command(
        env,
        service_mode="with_manager",
        accompaniment_ordinals=frozenset({1, 7}),
    )
    case = NativeCallerCase(
        "intake",
        env["pg"],
        env["clock"],
        dict(
            client=env["user"].user_id,
            admin=env["admin"].user_id,
            order=command.order_id,
        ),
        command,
    )
    try:
        await case.seed_native()
        yield case
    finally:
        await case.dispose()


@pytest_asyncio.fixture
async def native_work(collaboration_pg, financial_pg_engine):
    _, _, _, clock, data = collaboration_pg
    case = NativeCallerCase("work", financial_pg_engine, clock, data, None)
    try:
        await case.seed_native()
        yield case
    finally:
        await case.dispose()


async def mapping_first(case, operation, platform, change, evidence):
    await case.seed_operation(operation, platform)
    before = await case.snapshot()
    case.resolved, case.release_resolver = asyncio.Future(), asyncio.Event()
    case.transactions.entered = asyncio.Future()
    task = asyncio.create_task(case.post(operation, platform))
    try:
        proof = await asyncio.wait_for(case.resolved, 3)
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            field = "telegram_id" if platform == "telegram" else "max_id"
            await writer.execute(
                update(UserModel)
                .where(UserModel.user_id == proof.user_id)
                .values(
                    **{
                        field: None
                        if change in ("clear", "move")
                        else str(uuid4().int % 10**14 + 1)
                    }
                )
            )
            if change == "move":
                target = case.ids["manager" if case.kind == "work" else "admin"]
                await writer.execute(
                    update(UserModel)
                    .where(UserModel.user_id == target)
                    .values(**{field: proof.external_id})
                )
            async with observe_sql(case.factory) as observed:
                case.release_resolver.set()
                reader_pid = await asyncio.wait_for(
                    case.transactions.entered, 3
                )
                assert reader_pid != writer_pid
                blockers = await blocked_by(writer, reader_pid, writer_pid)
                assert not task.done()
                await writer.commit()
                response = await asyncio.wait_for(task, 4)
            assert response.status_code == 403, response.text
            assert response.json() == {"detail": "financial_principal_changed"}
            assert response.headers["cache-control"] == "no-store"
            expected = [
                case.ids[role]
                for role in ("client", "creator", "manager")
                if case.ids.get(role)
            ]
            assert_user_item_order(observed, expected)
            assert not [row for row in observed if row["kind"] == "item"]
        assert await case.snapshot() == before
        evidence.append(
            dict(
                case=case.kind + ":" + operation,
                direction="mapping_first",
                platform=platform,
                change=change,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                locks=observed,
                completed=True,
            )
        )
    finally:
        case.release_resolver.set()
        await finish(task)


async def authorization_first(case, operation, platform, evidence):
    await case.seed_operation(operation, platform)
    case.transactions.before_commit = asyncio.Future()
    case.transactions.release_commit = asyncio.Event()
    response_task = writer_task = None
    writer_started = asyncio.Future()
    actor = case.ids[case.actor_role]

    async def remap():
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            writer_started.set_result(writer_pid)
            field = "telegram_id" if platform == "telegram" else "max_id"
            await writer.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(**{field: None})
            )

    try:
        async with observe_sql(case.factory) as observed:
            response_task = asyncio.create_task(case.post(operation, platform))
            reader_pid = await asyncio.wait_for(
                case.transactions.before_commit, 3
            )
            writer_task = asyncio.create_task(remap())
            writer_pid = await asyncio.wait_for(writer_started, 3)
            assert writer_pid != reader_pid
            async with case.factory.begin() as observer:
                blockers = await blocked_by(observer, writer_pid, reader_pid)
            assert not response_task.done() and not writer_task.done()
            case.transactions.release_commit.set()
            response = await asyncio.wait_for(response_task, 4)
            await asyncio.wait_for(writer_task, 4)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        expected = [
            case.ids[role]
            for role in ("client", "creator", "manager")
            if case.ids.get(role)
        ]
        assert_user_item_order(observed, expected, case.ids.get("item"))
        evidence.append(
            dict(
                case=case.kind + ":" + operation,
                direction="authorization_first",
                platform=platform,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                locks=observed,
                completed=True,
            )
        )
    finally:
        case.transactions.release_commit.set()
        await finish(response_task)
        await finish(writer_task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["remap", "clear", "move"])
@pytest.mark.parametrize("operation", ["policies", "create", "replay"])
async def test_intake_mapping_first_uses_current_locked_native(
    native_intake, native_caller_evidence, platform, change, operation
):
    await mapping_first(
        native_intake, operation, platform, change, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["remap", "clear", "move"])
@pytest.mark.parametrize("operation", ["status", "command", "replay"])
async def test_work_mapping_first_uses_current_complete_native_scope(
    native_work, native_caller_evidence, platform, change, operation
):
    await mapping_first(
        native_work, operation, platform, change, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("operation", ["policies", "create", "replay"])
async def test_intake_authorization_first_holds_user_until_commit(
    native_intake, native_caller_evidence, platform, operation
):
    await authorization_first(
        native_intake, operation, platform, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("operation", ["status", "command", "replay"])
async def test_work_authorization_first_holds_complete_scope_until_commit(
    native_work, native_caller_evidence, platform, operation
):
    await authorization_first(
        native_work, operation, platform, native_caller_evidence
    )


@pytest.mark.asyncio
async def test_intake_same_canonical_tg_max_replay_keeps_original_receipt(
    native_intake,
):
    case = native_intake
    first = await case.post("create", "telegram")
    replay = await case.post("replay", "max")
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    snapshot = await case.snapshot()
    assert (
        len(snapshot["orders"]) == len(snapshot["order_intake_receipts"]) == 1
    )
    assert len(snapshot["order_items"]) == 30
    assert len(snapshot["accompaniment_leads"]) == 1


@pytest.mark.asyncio
async def test_work_same_canonical_tg_max_replay_keeps_hash_and_capabilities(
    native_work,
):
    case = native_work
    first = await case.post("command", "telegram")
    replay = await case.post("replay", "max")
    status = await case.post("status", "max")
    assert first.status_code == replay.status_code == status.status_code == 200
    assert first.json() == replay.json() == status.json()
    snapshot = await case.snapshot()
    assert len(snapshot["financial_collaborations"]) == 1
    assert len(snapshot["financial_collaboration_events"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["status", "role"])
async def test_intake_current_role_status_remain_authoritative(
    native_intake, platform, change
):
    case = native_intake
    before = await case.snapshot()
    async with case.factory.begin() as db:
        if change == "role":
            await db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == case.ids["client"]
                )
            )
        else:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == case.ids["client"])
                .values(status="blocked")
            )
    for operation in ("policies", "create"):
        response = await case.post(operation, platform)
        assert response.status_code == 403
        assert response.json() == {"detail": "active_advertiser_required"}
        assert response.headers["cache-control"] == "no-store"
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["status", "role", "membership"])
async def test_work_current_role_status_and_manager_membership(
    native_work, platform, change
):
    case = native_work
    await case.seed_operation("status", platform)
    before = await case.snapshot()
    async with case.factory.begin() as db:
        if change == "membership":
            case.actor_role = "manager"
            await db.execute(
                delete(ManagerOrderModel).where(
                    ManagerOrderModel.user_id == case.ids["manager"],
                    ManagerOrderModel.order_id == case.ids["order"],
                )
            )
        elif change == "role":
            await db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == case.ids["client"]
                )
            )
        else:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == case.ids["client"])
                .values(status="blocked")
            )
    response = await case.post("status", platform)
    assert response.status_code == 403
    assert response.json() == {
        "detail": "active_actor_required"
        if change == "status"
        else "collaboration_view_forbidden"
    }
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_intake_unknown_identity_and_max_missing_country_create_nothing(
    native_intake, platform
):
    case = native_intake
    before = await case.snapshot()
    async with case.factory.begin() as db:
        users_before = await db.scalar(
            select(func.count()).select_from(UserModel)
        )
    _, payload = case.request("create", platform)
    payload.update(case.auth(platform, native=str(uuid4().int % 10**14 + 1)))
    response = await case.post("create", platform, payload=payload)
    assert response.status_code == 404
    assert response.json() == {"detail": "existing_financial_account_required"}
    assert response.headers["cache-control"] == "no-store"
    async with case.factory.begin() as db:
        assert (
            await db.scalar(select(func.count()).select_from(UserModel))
            == users_before
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == case.ids["client"])
            .values(country=None)
        )
    policies = await case.post("policies", "max")
    assert policies.status_code == 200
    assert policies.json() == {
        "currency": "",
        "writes_paused": False,
        "policies": [],
    }
    created = await case.post("create", "max")
    assert created.status_code == 400
    assert created.json() == {"detail": "unpublished_currency"}
    async with case.factory.begin() as db:
        assert (
            await db.scalar(
                select(UserModel.country).where(
                    UserModel.user_id == case.ids["client"]
                )
            )
            is None
        )
        assert (
            await db.scalar(select(func.count()).select_from(UserModel))
            == users_before
        )
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_unknown_signed_identity_never_creates_account_or_work(
    native_work, platform
):
    case = native_work
    before = await case.snapshot()
    async with case.factory.begin() as db:
        count = await db.scalar(select(func.count()).select_from(UserModel))
    _, payload = case.request("command", platform)
    payload.update(case.auth(platform, native=str(uuid4().int % 10**14 + 1)))
    response = await case.post("command", platform, payload=payload)
    assert response.status_code == 404
    assert response.json() == {"detail": "existing_financial_account_required"}
    async with case.factory.begin() as db:
        assert (
            await db.scalar(select(func.count()).select_from(UserModel))
            == count
        )
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_no_manager_uses_only_complete_current_user_set(
    native_work, platform
):
    from ugc_bot.infrastructure.db.models import ItemAssignmentModel

    case = native_work
    async with case.factory.begin() as db:
        await db.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == case.ids["assignment"])
            .values(manager_id=None)
        )
    async with observe_sql(case.factory) as observed:
        response = await case.post("command", platform)
    assert response.status_code == 200, response.text
    assert_user_item_order(
        observed, [case.ids["client"], case.ids["creator"]], case.ids["item"]
    )
    assert response.json()["record"]["collaboration"]["manager_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("actor_first", [True, False])
async def test_work_foreign_admin_locks_sorted_users_before_item_and_denies(
    native_work, actor_first
):
    from uuid import UUID

    from ugc_bot.domain.enums import MessengerType

    case = native_work
    await case.seed_operation("status", "telegram")
    parties = [case.ids[role] for role in ("client", "creator", "manager")]
    actor = UUID(
        int=min(uid.int for uid in parties) - 1
        if actor_first
        else max(uid.int for uid in parties) + 1
    )
    native = tuple(str(uuid4().int % 10**14 + 1) for _ in range(2))
    async with case.factory.begin() as db:
        db.add(
            UserModel(
                user_id=actor,
                messenger_type=MessengerType.TELEGRAM,
                username="synthetic outsider",
                status="active",
                admin=True,
                telegram_id=native[0],
                max_id=native[1],
            )
        )
    case.ids["outsider"], case.native["outsider"], case.actor_role = (
        actor,
        native,
        "outsider",
    )
    before = await case.snapshot()
    async with observe_sql(case.factory) as observed:
        response = await case.post("status", "telegram")
    assert response.status_code == 403
    assert response.json() == {"detail": "collaboration_view_forbidden"}
    assert_user_item_order(observed, [*parties, actor], case.ids["item"])
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_initial_absence_does_not_fall_through_after_real_user_wait(
    native_work, native_caller_evidence, platform
):
    from sqlalchemy import insert

    from ugc_bot.infrastructure.db.models import ItemAssignmentModel

    case = native_work
    async with case.factory.begin() as db:
        source = dict(
            (
                await db.execute(
                    select(ItemAssignmentModel.__table__).where(
                        ItemAssignmentModel.assignment_id
                        == case.ids["assignment"]
                    )
                )
            )
            .mappings()
            .one()
        )
        await db.execute(
            delete(ItemAssignmentModel).where(
                ItemAssignmentModel.assignment_id == case.ids["assignment"]
            )
        )
    case.transactions.entered = asyncio.Future()
    task = None
    try:
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            await writer.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == case.ids["client"])
                .with_for_update(key_share=True)
            )
            async with observe_sql(case.factory) as observed:
                task = asyncio.create_task(case.post("status", platform))
                reader_pid = await asyncio.wait_for(
                    case.transactions.entered, 3
                )
                assert reader_pid != writer_pid
                blockers = await blocked_by(writer, reader_pid, writer_pid)
                await writer.execute(
                    insert(ItemAssignmentModel).values(**source)
                )
                await writer.commit()
                response = await asyncio.wait_for(task, 4)
        assert response.status_code == 404
        assert response.json() == {"detail": "collaboration_not_found"}
        assert_user_item_order(observed, [case.ids["client"]])
        assert not [row for row in observed if row["kind"] == "item"]
        async with case.factory.begin() as db:
            assert (
                await db.get(ItemAssignmentModel, case.ids["assignment"])
                is not None
            )
        assert not (await case.snapshot())["financial_collaboration_events"]
        native_caller_evidence.append(
            dict(
                case="work:initial_absence",
                platform=platform,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                completed=True,
            )
        )
    finally:
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["commit", "rollback"])
async def test_work_prepared_scope_refuses_finished_and_other_real_roots(
    native_work, end
):
    case = native_work
    repo = case.service.repository
    proof = AuthenticatedMessengerPrincipal(
        case.ids["client"], "telegram", case.native["client"][0]
    )
    async with case.factory() as db:
        await db.begin()
        prepared = await repo.prepare_principal_scope(
            case.ids["assignment"], proof.user_id, proof, session=db
        )
        await getattr(db, end)()
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.lock_scope(
                case.ids["assignment"], session=db, expected_scope=prepared
            )
        await db.begin()
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.lock_scope(
                case.ids["assignment"], session=db, expected_scope=prepared
            )
        async with case.factory.begin() as other:
            with pytest.raises(ValueError, match="caller_transaction_required"):
                await repo.lock_scope(
                    case.ids["assignment"],
                    session=other,
                    expected_scope=prepared,
                )


@pytest.mark.asyncio
async def test_work_nested_preparation_refuses_before_any_scope_query(
    native_work,
):
    case = native_work
    proof = AuthenticatedMessengerPrincipal(
        case.ids["client"], "telegram", case.native["client"][0]
    )
    async with (
        case.transactions.transaction() as db,
        db.begin_nested(),
        observe_sql(case.factory) as observed,
    ):
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await case.service.repository.prepare_principal_scope(
                case.ids["assignment"], proof.user_id, proof, session=db
            )
        assert observed == []


@pytest_asyncio.fixture
async def alternate_work(financial_pg_engine, request):
    """A second source uses the existing complete paid fixture."""
    async for value in collaboration_pg.__wrapped__(
        financial_pg_engine, request
    ):
        yield value


async def change_work_source(case, writer, alternate, change):
    from ugc_bot.infrastructure.db.models import (
        ItemAssignmentModel,
        OrderModel,
    )

    if change == "disappear":
        await writer.execute(
            delete(ItemAssignmentModel).where(
                ItemAssignmentModel.assignment_id == case.ids["assignment"]
            )
        )
        return
    if change == "creator":
        values = dict(creator_id=alternate["creator"])
    elif change == "swap":
        values = dict(
            creator_id=case.ids["manager"], manager_id=case.ids["creator"]
        )
    elif change == "client":
        await writer.execute(
            update(OrderModel)
            .where(OrderModel.order_id == case.ids["order"])
            .values(advertiser_id=case.ids["manager"])
        )
        return
    else:
        await writer.execute(
            update(ItemAssignmentModel)
            .where(ItemAssignmentModel.assignment_id == alternate["assignment"])
            .values(valid_to=case.clock.now())
        )
        values = dict(paid_item_id=alternate["item"], version=2)
    await writer.execute(
        update(ItemAssignmentModel)
        .where(ItemAssignmentModel.assignment_id == case.ids["assignment"])
        .values(**values)
    )


async def source_changes_during_item_wait(
    case, alternate, platform, change, evidence
):
    from ugc_bot.infrastructure.db.models import OrderItemModel, OrderModel

    async with case.factory.begin() as db:
        await db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == alternate["order"])
            .values(advertiser_id=case.ids["client"])
        )
    before = await case.snapshot()
    case.transactions.entered = asyncio.Future()
    task = None
    try:
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            await writer.execute(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.paid_item_id == case.ids["item"])
                .with_for_update()
            )
            async with observe_sql(case.factory) as observed:
                task = asyncio.create_task(case.post("command", platform))
                reader_pid = await asyncio.wait_for(
                    case.transactions.entered, 3
                )
                assert reader_pid != writer_pid
                blockers = await blocked_by(writer, reader_pid, writer_pid)
                await change_work_source(case, writer, alternate, change)
                await writer.commit()
                response = await asyncio.wait_for(task, 4)
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": "collaboration_scope_changed"}
        assert response.headers["cache-control"] == "no-store"
        assert_user_item_order(
            observed,
            [case.ids[role] for role in ("client", "creator", "manager")],
            case.ids["item"],
        )
        assert await case.snapshot() == before
        evidence.append(
            dict(
                case="work:source_change:" + change,
                platform=platform,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                locks=observed,
                completed=True,
            )
        )
    finally:
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "change", ["creator", "swap", "client", "item", "disappear"]
)
async def test_work_post_wait_exact_source_refuses_new_or_same_user_set(
    native_work, alternate_work, native_caller_evidence, platform, change
):
    await source_changes_during_item_wait(
        native_work, alternate_work[4], platform, change, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_captured_item_order_rewrite_is_23514_and_scope_stays_valid(
    native_work, alternate_work, native_caller_evidence, platform
):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.models import OrderItemModel

    case = native_work
    with pytest.raises(
        IntegrityError, match="captured_item_immutable"
    ) as error:
        async with case.factory.begin() as writer:
            await writer.execute(
                update(OrderItemModel)
                .where(OrderItemModel.paid_item_id == case.ids["item"])
                .values(order_id=alternate_work[4]["order"], ordinal=2)
            )
    assert error.value.orig.sqlstate == "23514"
    async with case.factory.begin() as db:
        assert (
            await db.scalar(
                select(OrderItemModel.order_id).where(
                    OrderItemModel.paid_item_id == case.ids["item"]
                )
            )
            == case.ids["order"]
        )
    response = await case.post("command", platform)
    assert response.status_code == 200, response.text
    native_caller_evidence.append(
        dict(
            case="work:captured_order_immutable",
            platform=platform,
            sqlstate="23514",
            unchanged_order=True,
            completed=True,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "command"])
async def test_work_reentrant_load_refuses_changed_item_before_choosing_lock(
    native_work, alternate_work, monkeypatch, operation, native_caller_evidence
):
    from ugc_bot.infrastructure.db.models import ItemAssignmentModel

    case, other = native_work, alternate_work[4]
    repo = case.service.repository
    original = repo.prepare_principal_scope
    calls = []

    async def prepare(*args, session, **kwargs):
        prepared = await original(*args, session=session, **kwargs)
        calls.append(prepared)
        reader_pid = await backend_pid(session)
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            assert writer_pid != reader_pid
            await writer.execute(
                update(ItemAssignmentModel)
                .where(ItemAssignmentModel.assignment_id == other["assignment"])
                .values(valid_to=case.clock.now())
            )
            await writer.execute(
                update(ItemAssignmentModel)
                .where(
                    ItemAssignmentModel.assignment_id == case.ids["assignment"]
                )
                .values(paid_item_id=other["item"], version=2)
            )
        native_caller_evidence.append(
            dict(
                case="work:reentrant_item:" + operation,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                completed=True,
            )
        )
        return prepared

    monkeypatch.setattr(repo, "prepare_principal_scope", prepare)
    before = await case.snapshot()
    async with observe_sql(case.factory) as observed:
        response = await case.post(operation, "telegram")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "collaboration_scope_changed"}
    assert len(calls) == 1
    assert_user_item_order(
        observed,
        [case.ids[role] for role in ("client", "creator", "manager")],
        case.ids["item"],
    )
    assert len([row for row in observed if row["kind"] == "item"]) == 1
    assert await case.snapshot() == before


@pytest.mark.asyncio
async def test_work_capabilities_reuse_preparation_and_recheck_named_source(
    native_work, monkeypatch
):
    from ugc_bot.infrastructure.db.models import OrderModel

    case = native_work
    repo = case.service.repository
    prepare, persist = repo.prepare_principal_scope, repo.persist
    prepared = []

    async def once(*args, **kwargs):
        result = await prepare(*args, **kwargs)
        prepared.append(result)
        return result

    async def change_after_write(*args, session, **kwargs):
        await persist(*args, session=session, **kwargs)
        await session.execute(
            update(OrderModel)
            .where(OrderModel.order_id == case.ids["order"])
            .values(advertiser_id=case.ids["manager"])
        )

    monkeypatch.setattr(repo, "prepare_principal_scope", once)
    monkeypatch.setattr(repo, "persist", change_after_write)
    before = await case.snapshot()
    async with observe_sql(case.factory) as observed:
        response = await case.post("command", "telegram")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "collaboration_scope_changed"}
    assert len(prepared) == 1
    assert_user_item_order(observed, prepared[0].user_ids, case.ids["item"])
    assert len([row for row in observed if row["kind"] == "item"]) == 3
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["actor_id", "system_actor", "is_admin", "external_id"]
)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_work_sql_http_never_accepts_public_authority_or_system_fields(
    native_work, field, platform
):
    case = native_work
    before = await case.snapshot()
    _, payload = case.request("command", platform)
    response = await case.post(
        "command",
        platform,
        payload=payload | {field: "SYNTHETIC_PRIVATE_AUTHORITY"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "collaboration_request_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["client_id", "principal", "selection_minor"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_intake_sql_http_never_accepts_public_identity_or_price_authority(
    native_intake, field, platform
):
    case = native_intake
    before = await case.snapshot()
    _, payload = case.request("create", platform)
    response = await case.post(
        "create",
        platform,
        payload=payload | {field: "SYNTHETIC_PRIVATE_AUTHORITY"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "intake_request_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert await case.snapshot() == before


async def role_changes_before_barrier(case, platform, change, evidence):
    operation = "replay" if case.kind == "intake" else "status"
    await case.seed_operation(operation, platform)
    if change == "membership":
        case.actor_role = "manager"
    before = await case.snapshot()
    case.resolved, case.release_resolver = asyncio.Future(), asyncio.Event()
    case.transactions.entered = asyncio.Future()
    task = asyncio.create_task(case.post(operation, platform))
    try:
        proof = await asyncio.wait_for(case.resolved, 3)
        async with case.factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            await writer.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == proof.user_id)
                .with_for_update(key_share=True)
            )
            if change == "status":
                await writer.execute(
                    update(UserModel)
                    .where(UserModel.user_id == proof.user_id)
                    .values(status="blocked")
                )
            elif change == "membership":
                await writer.execute(
                    delete(ManagerOrderModel).where(
                        ManagerOrderModel.user_id == proof.user_id,
                        ManagerOrderModel.order_id == case.ids["order"],
                    )
                )
            else:
                await writer.execute(
                    delete(AdvertiserProfileModel).where(
                        AdvertiserProfileModel.user_id == proof.user_id
                    )
                )
            async with observe_sql(case.factory) as observed:
                case.release_resolver.set()
                reader_pid = await asyncio.wait_for(
                    case.transactions.entered, 3
                )
                assert reader_pid != writer_pid
                blockers = await blocked_by(writer, reader_pid, writer_pid)
                await writer.commit()
                response = await asyncio.wait_for(task, 4)
        assert response.status_code == 403, response.text
        code = (
            "active_advertiser_required"
            if case.kind == "intake"
            else "active_actor_required"
            if change == "status"
            else "collaboration_view_forbidden"
        )
        assert response.json() == {"detail": code}
        assert response.headers["cache-control"] == "no-store"
        assert await case.snapshot() == before
        evidence.append(
            dict(
                case=case.kind + ":current_" + change,
                platform=platform,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                locks=observed,
                completed=True,
            )
        )
    finally:
        case.release_resolver.set()
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["status", "role"])
async def test_intake_current_authority_committed_during_real_user_wait(
    native_intake, platform, change, native_caller_evidence
):
    await role_changes_before_barrier(
        native_intake, platform, change, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["status", "role", "membership"])
async def test_work_current_authority_committed_during_real_user_wait(
    native_work, platform, change, native_caller_evidence
):
    await role_changes_before_barrier(
        native_work, platform, change, native_caller_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_capture_and_assignment_producers_support_native_work(
    capture_env, monkeypatch, platform
):
    from types import SimpleNamespace

    from tests.postgres_financial.test_work_entitlement_runtime import (
        start_flow,
    )

    env = capture_env
    case = None
    try:
        flow = await start_flow(env, monkeypatch)
        ids = dict(
            client=env["client"],
            creator=flow["creator"],
            manager=flow["manager"],
            order=env["order"],
            item=flow["item"],
            assignment=flow["assignment"],
        )
        clock = SimpleNamespace(now=lambda: flow["clock"].at)
        case = NativeCallerCase("work", env["pg"], clock, ids, None)
        await case.seed_native()
        status = await case.post("status", platform)
        assert status.status_code == 200, status.text
        assert status.json()["is_current"] is True
        assert status.json()["record"]["paid_item_id"] == str(flow["item"])
        payload = case.auth(platform) | dict(
            action="start",
            operation_key="native-captured-start",
            expected_version=1,
        )
        async with observe_sql(case.factory) as observed:
            response = await case.post("command", platform, payload=payload)
        assert response.status_code == 200, response.text
        assert (
            response.json()["record"]["collaboration"]["state"] == "in_progress"
        )
        assert_user_item_order(
            observed,
            [ids[role] for role in ("client", "creator", "manager")],
            ids["item"],
        )
    finally:
        if case is not None:
            await case.dispose()
        for container in env.get("_work_containers", ()):
            await container.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_first", [False, True])
async def test_actual_notice_and_sweep_retain_trusted_item_only_contract(
    collaboration_pg, monkeypatch, failed_first
):
    from tests.helpers.native_caller_pg import ObservedTransactions
    from tests.postgres_financial.test_notice_delivery_persistence import (
        dispatch,
        environment,
    )
    from ugc_bot.application.notice_delivery_ports import DeliveryFailure
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )
    from ugc_bot.infrastructure.db.notice_delivery_models import (
        NoticeDeliveryAttemptModel,
        NoticeDeliveryOutcomeModel,
    )

    worker, _, transport, notice_ids = await environment(collaboration_pg)
    factory, _, _, clock, data = collaboration_pg
    original_transport = transport
    worker.transactions = ObservedTransactions(worker.transactions)

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "trusted notice/sweep acquired public principal scope"
        )

    monkeypatch.setattr(
        worker.lifecycle.repository, "prepare_principal_scope", forbidden
    )
    async with observe_sql(factory) as observed:
        if failed_first:

            class Failure:
                async def send(self, attempt):
                    raise DeliveryFailure("provider_rejected", uncertain=False)

            worker.transport = Failure()
            await dispatch(worker, notice_ids[0])
            worker.transport = original_transport
            await worker.retry_notice(
                notice_ids[0],
                actor_id=data["manager"],
                reason="reviewed test contact",
                operation_key="native-notice-retry:" + uuid4().hex,
            )
            clock.at += timedelta(minutes=1)
        await dispatch(worker, notice_ids[0])
        clock.at += timedelta(hours=73)
        sweep = await CollaborationSweepService(
            worker.lifecycle, worker.transactions
        ).run_once()
    assert not [row for row in observed if row["kind"] == "user"]
    assert len(original_transport.sent) == 1
    async with factory.begin() as db:
        record = await worker.lifecycle.repository.get(
            data["assignment"], session=db
        )
        outcomes = (
            await db.execute(
                select(
                    NoticeDeliveryOutcomeModel.status,
                    NoticeDeliveryOutcomeModel.provider_reference,
                    NoticeDeliveryOutcomeModel.applied,
                )
                .join(
                    NoticeDeliveryAttemptModel,
                    NoticeDeliveryAttemptModel.attempt_id
                    == NoticeDeliveryOutcomeModel.attempt_id,
                )
                .where(
                    NoticeDeliveryAttemptModel.assignment_id
                    == data["assignment"],
                    NoticeDeliveryOutcomeModel.kind == "transport",
                )
            )
        ).all()
    assert all(row.applied for row in outcomes)
    assert {row.status for row in outcomes} == (
        {"failed", "accepted"} if failed_first else {"accepted"}
    )
    assert [
        row.provider_reference for row in outcomes if row.status == "accepted"
    ] == ["actual-synthetic-provider-reference"]
    assert record.collaboration.notice_delivered_at is not None
    assert (record.collaboration.notice_failed_at is not None) == failed_first
    assert record.collaboration.state.value == (
        "success_claimed" if failed_first else "success_final"
    )
    assert sweep.changed == int(not failed_first)


async def mounted_success_and_stale_native_denial(case, platform, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from ugc_bot.miniapp.api import router

    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = case.container._config
    app.state.dispatcher = case.services
    operation = "create" if case.kind == "intake" else "command"
    path, payload = case.request(operation, platform)
    roles = case.services["user_role_service"]
    original = roles.get_user

    async def changed_after_real_lookup(self, *args, **kwargs):
        # The real signed resolver receives its real SQL-loaded User snapshot.
        # A committed remap precedes the independent service User barrier.
        user = await original(*args, **kwargs)
        async with case.factory.begin() as writer:
            field = "telegram_id" if platform == "telegram" else "max_id"
            await writer.execute(
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(**{field: None})
            )
        return user

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        success = await client.post("/miniapp/api" + path, json=payload)
        assert success.status_code == 200, success.text
        assert success.headers["cache-control"] == "no-store"
        before = await case.snapshot()
        monkeypatch.setattr(type(roles), "get_user", changed_after_real_lookup)
        denied = await client.post("/miniapp/api" + path, json=payload)
    assert denied.status_code == 403, denied.text
    assert denied.json() == {"detail": "financial_principal_changed"}
    assert denied.headers["cache-control"] == "no-store"
    assert await case.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_mounted_intake_uses_production_typed_resolver_injection(
    native_intake, platform, monkeypatch
):
    await mounted_success_and_stale_native_denial(
        native_intake, platform, monkeypatch
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_mounted_work_uses_production_typed_resolver_injection(
    native_work, platform, monkeypatch
):
    await mounted_success_and_stale_native_denial(
        native_work, platform, monkeypatch
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_intake_sql_uuid_proof_mismatch_cannot_replay_client_receipt(
    native_intake, platform
):
    case = native_intake
    await case.seed_operation("replay", platform)
    before = await case.snapshot()
    proof = AuthenticatedMessengerPrincipal(
        case.ids["admin"], platform, case.native["client"][platform == "max"]
    )
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await case.service.create(case.command, principal=proof)
    assert await case.snapshot() == before


@pytest.mark.asyncio
async def test_work_expected_assignment_scope_refuses_before_sql(native_work):
    case = native_work
    proof = AuthenticatedMessengerPrincipal(
        case.ids["client"], "telegram", case.native["client"][0]
    )
    async with case.transactions.transaction() as db:
        prepared = await case.service.repository.prepare_principal_scope(
            case.ids["assignment"], proof.user_id, proof, session=db
        )
        async with observe_sql(case.factory) as observed:
            with pytest.raises(ValueError, match="collaboration_scope_changed"):
                await case.service.repository.lock_scope(
                    uuid4(), session=db, expected_scope=prepared
                )
        assert observed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_mounted_legacy_rating_carry_uses_actual_actor_and_sql(
    native_work, platform
):
    """Cover central-router compatibility with real rating facts and roles."""
    import httpx
    from fastapi import FastAPI

    from ugc_bot.infrastructure.db.models import BloggerRatingModel
    from ugc_bot.miniapp.api import router

    case = native_work
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = case.container._config
    app.state.dispatcher = case.services
    path = "/miniapp/api/ratings"
    payload = dict(
        case.auth(platform),
        blogger_id=str(case.ids["creator"]),
        order_id=str(case.ids["order"]),
        score=4,
        comment="Approved synthetic work",
    )
    before = await case.snapshot()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        missing = await client.post(
            path, json=payload | dict(order_id=str(uuid4()))
        )
        assert missing.status_code == 404, missing.text
        assert missing.json() == {"detail": "Order not found"}
        forbidden = await client.post(
            path, json=payload | case.auth(platform, role="creator")
        )
        assert forbidden.status_code == 403, forbidden.text
        async with case.factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(BloggerRatingModel)
                    .where(BloggerRatingModel.order_id == case.ids["order"])
                )
                == 0
            )
        created = await client.post(path, json=payload)
        assert created.status_code == 200, created.text
        assert created.json()["ok"] is True
        duplicate = await client.post(path, json=payload)
        assert duplicate.status_code == 409, duplicate.text
        rating = await client.get(
            f"/miniapp/api/bloggers/{case.ids['creator']}/rating",
            params=case.auth(platform),
        )
        assert rating.status_code == 200, rating.text
    async with case.factory() as db:
        persisted = (
            await db.execute(
                select(BloggerRatingModel).where(
                    BloggerRatingModel.order_id == case.ids["order"]
                )
            )
        ).scalar_one()
        assert str(persisted.rating_id) == created.json()["rating_id"]
        assert persisted.blogger_id == case.ids["creator"]
        assert persisted.rater_id == case.ids["client"]
        assert persisted.rater_role.value == "advertiser"
        assert persisted.score == 4
        assert persisted.comment == payload["comment"]
    assert rating.json() == {
        "avg_rating": 4.0,
        "ratings": [
            dict(
                rating_id=str(persisted.rating_id),
                blogger_id=str(case.ids["creator"]),
                order_id=str(case.ids["order"]),
                rater_id=str(case.ids["client"]),
                rater_role="advertiser",
                score=4,
                comment=payload["comment"],
                created_at=persisted.created_at.isoformat(),
            )
        ],
    }
    assert await case.snapshot() == before
