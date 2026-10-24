"""Persisted lifecycle commands, independent of transport and wallet I/O."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.domain.collaboration import CollaborationState


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 23, tzinfo=timezone.utc)

    def now(self):
        return self.at


def setup_lifecycle():
    try:
        from ugc_bot.application.collaboration_ports import (
            CollaborationActor,
            CollaborationCommand,
            CollaborationScope,
        )
        from ugc_bot.application.services.collaboration_service import (
            CollaborationService,
        )
        from ugc_bot.infrastructure.memory_collaborations import (
            InMemoryCollaborationRepository,
        )
    except ModuleNotFoundError:
        pytest.fail("Persisted collaboration command component is missing")
    clock = Clock()
    assignment, item, order, client, creator, manager, stranger = [
        uuid4() for _ in range(7)
    ]
    scope = CollaborationScope(
        assignment_id=assignment,
        paid_item_id=item,
        order_id=order,
        client_id=client,
        creator_id=creator,
        manager_id=manager,
        policy_version="approved-synthetic",
        captured_at=clock.at - timedelta(days=1),
        valid_from=clock.at - timedelta(hours=1),
        valid_to=None,
        selection_funded=True,
    )
    actors = {
        client: CollaborationActor(client, "active", is_client=True),
        creator: CollaborationActor(creator, "active", is_creator=True),
        manager: CollaborationActor(
            manager, "active", manager_order_ids=(order,)
        ),
        stranger: CollaborationActor(stranger, "active", is_admin=True),
    }
    repository = InMemoryCollaborationRepository({assignment: scope}, actors)
    service = CollaborationService(repository, clock)
    return service, repository, scope, clock, CollaborationCommand, stranger


async def execute(service, repository, command):
    async with repository.transaction() as session:
        return await service.execute(command, session=session)


async def started():
    service, repo, scope, clock, Command, stranger = setup_lifecycle()
    assigned = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="assign",
            actor_id=scope.client_id,
            operation_key="agree-brief",
            expected_version=0,
            due_at=clock.at + timedelta(days=2),
            terms_reference="agreed-brief:123",
        ),
    )
    result = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="start",
            actor_id=scope.manager_id,
            operation_key="start",
            expected_version=assigned.version,
        ),
    )
    return service, repo, scope, clock, Command, stranger, result


@pytest.mark.asyncio
async def test_claim_persists_first_origin_and_one_opposite_party_notice():
    service, repo, scope, clock, Command, _, current = await started()
    command = Command(
        assignment_id=scope.assignment_id,
        action="claim",
        actor_id=scope.creator_id,
        operation_key="first-claim",
        expected_version=current.version,
        evidence="https://example.com/content/123",
    )
    first = await execute(service, repo, command)
    clock.at += timedelta(hours=1)
    retry = await execute(service, repo, command)
    assert retry == first
    assert first.collaboration.state == CollaborationState.SUCCESS_CLAIMED
    assert first.collaboration.claimant_id == scope.creator_id
    assert first.collaboration.claimed_at == datetime(
        2026, 10, 23, tzinfo=timezone.utc
    )
    notices = list(repo.notices.values())
    assert len(notices) == 1
    assert notices[0].recipient_id == scope.client_id
    assert notices[0].purpose == "objection"
    assert len(repo.events) == 3
    assert len(repo.outbox) == 4
    assert not repo.schedules
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await execute(service, repo, replace(command, evidence="changed"))


@pytest.mark.asyncio
async def test_manager_and_admin_cannot_claim_either_partys_success():
    service, repo, scope, _, Command, stranger, current = await started()
    for actor in (scope.manager_id, stranger):
        with pytest.raises(
            PermissionError, match="collaboration_party_required"
        ):
            await execute(
                service,
                repo,
                Command(
                    assignment_id=scope.assignment_id,
                    action="claim",
                    actor_id=actor,
                    operation_key=str(actor),
                    expected_version=current.version,
                    evidence="manager cannot approve own reward",
                ),
            )
    assert len(repo.events) == 2


@pytest.mark.asyncio
async def test_current_role_removal_denies_stale_manager_command():
    service, repo, scope, _, Command, _, current = await started()
    repo.actors[scope.manager_id] = replace(
        repo.actors[scope.manager_id], manager_order_ids=()
    )
    with pytest.raises(PermissionError, match="assignment_actor_required"):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="request_confirmation",
                actor_id=scope.manager_id,
                operation_key="request-after-removal",
                expected_version=current.version,
            ),
        )
    assert len(repo.events) == 2


async def claimed():
    service, repo, scope, clock, Command, stranger, current = await started()
    current = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="claim",
            actor_id=scope.creator_id,
            operation_key="claim",
            expected_version=current.version,
            evidence="proof:content",
        ),
    )
    return service, repo, scope, clock, Command, stranger, current


def system_command(Command, scope, current, action, key, **kwargs):
    return Command(
        assignment_id=scope.assignment_id,
        action=action,
        operation_key=key,
        expected_version=current.version,
        system_actor=(
            "collaboration_notifier"
            if action == "notice"
            else "collaboration_scheduler"
        ),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_notice_failure_survives_later_accepted_retry():
    service, repo, scope, clock, Command, _, current = await claimed()
    notice = next(iter(repo.notices.values()))
    for accepted, key in ((False, "failed"), (True, "retry-accepted")):
        current = await execute(
            service,
            repo,
            system_command(
                Command,
                scope,
                current,
                "notice",
                key,
                notice_id=notice.notice_id,
                accepted=accepted,
                channel="telegram",
                external_reference="message:17" if accepted else None,
                reason=None if accepted else "bot blocked",
            ),
        )
    clock.at += timedelta(hours=73)
    current = await execute(
        service,
        repo,
        system_command(Command, scope, current, "advance", "tick-73h"),
    )
    assert current.collaboration.state == CollaborationState.SUCCESS_CLAIMED
    assert current.collaboration.notice_failed_at is not None
    assert not repo.schedules
    current = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="agree",
            actor_id=scope.client_id,
            operation_key="explicit-opposite-consent",
            expected_version=current.version,
        ),
    )
    assert current.collaboration.state == CollaborationState.SUCCESS_FINAL
    schedule = next(iter(repo.schedules.values()))
    assert schedule.success_final_at == clock.at
    assert schedule.release_at == clock.at + timedelta(days=14)


@pytest.mark.asyncio
async def test_scheduler_persists_final_schedule_then_separate_maturity():
    service, repo, scope, clock, Command, _, current = await claimed()
    notice = next(iter(repo.notices.values()))
    current = await execute(
        service,
        repo,
        system_command(
            Command,
            scope,
            current,
            "notice",
            "notice-accepted",
            notice_id=notice.notice_id,
            accepted=True,
            channel="max",
            external_reference="max:message:1",
        ),
    )
    clock.at += timedelta(hours=72)
    async with repo.transaction() as session:
        assert (await repo.list_due(clock.at, 10, session=session))[
            0
        ].version == current.version
    current = await execute(
        service,
        repo,
        system_command(Command, scope, current, "advance", "finalize"),
    )
    final_time = clock.at
    assert current.collaboration.state == CollaborationState.SUCCESS_FINAL
    assert len(repo.schedules) == 1
    assert next(
        iter(repo.schedules.values())
    ).release_at == final_time + timedelta(days=14)
    clock.at += timedelta(days=14)
    current = await execute(
        service,
        repo,
        system_command(Command, scope, current, "advance", "mature"),
    )
    assert current.collaboration.state == CollaborationState.AVAILABLE
    assert len(repo.schedules) == 1
    assert {event.event_type for event in repo.events.values()} >= {
        "financial.collaboration.success_final",
        "financial.collaboration.hold_matured",
    }


@pytest.mark.asyncio
async def test_reasoned_71_hour_dispute_persists_case_without_maturity():
    service, repo, scope, clock, Command, _, current = await claimed()
    clock.at += timedelta(hours=71)
    current = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="dispute",
            actor_id=scope.client_id,
            operation_key="dispute-71h",
            expected_version=current.version,
            reason="wrong product in content",
        ),
    )
    assert current.collaboration.state == CollaborationState.DISPUTED
    event = list(repo.events.values())[-1]
    assert event.parameters["reason"] == "wrong product in content"
    assert event.parameters["case_id"]
    assert not repo.schedules


@pytest.mark.asyncio
async def test_silent_expiration_is_auditable_and_never_gets_release_schedule():
    service, repo, scope, clock, Command, _, current = await started()
    clock.at += timedelta(days=16)
    current = await execute(
        service,
        repo,
        system_command(Command, scope, current, "advance", "expire"),
    )
    assert current.collaboration.state == CollaborationState.UNCONFIRMED_EXPIRED
    assert (
        list(repo.events.values())[-1].event_type
        == "financial.collaboration.expired"
    )
    assert not repo.schedules


@pytest.mark.asyncio
async def test_due_extension_preserves_first_claim_and_exact_objection_window():
    service, repo, scope, clock, Command, _, current = await claimed()
    original = current.collaboration
    clock.at += timedelta(hours=1)
    current = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="extend_due",
            actor_id=scope.client_id,
            operation_key="agreed-extension",
            expected_version=current.version,
            expected_due_version=1,
            due_at=clock.at + timedelta(days=7),
            terms_reference="extension-consent:1",
            reason="shipment late",
        ),
    )
    assert current.collaboration.due_version == 2
    assert current.collaboration.claimed_at == original.claimed_at
    assert (
        current.collaboration.objection_deadline == original.objection_deadline
    )
    assert (
        list(repo.events.values())[-1].parameters["terms_reference"]
        == "extension-consent:1"
    )


@pytest.mark.asyncio
async def test_manager_confirmation_request_deduplicates_notification_purpose():
    service, repo, scope, _, Command, _, current = await started()
    for key in ("request", "double-click-with-new-key"):
        current = await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="request_confirmation",
                actor_id=scope.manager_id,
                operation_key=key,
                expected_version=current.version,
            ),
        )
    assert len(repo.notices) == 2
    assert {notice.recipient_id for notice in repo.notices.values()} == {
        scope.client_id,
        scope.creator_id,
    }
    assert current.collaboration.state == CollaborationState.IN_PROGRESS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,error",
    [
        (
            {"valid_to": datetime(2026, 10, 23, tzinfo=timezone.utc)},
            "assignment_not_current",
        ),
        ({"captured_at": None}, "captured_selection_required"),
        ({"selection_funded": False}, "captured_selection_required"),
        ({"policy_version": None}, "captured_selection_required"),
    ],
)
async def test_rejects_closed_or_unfunded_assignment(change, error):
    service, repo, scope, clock, Command, _ = setup_lifecycle()
    repo.scopes[scope.assignment_id] = replace(scope, **change)
    with pytest.raises(ValueError, match=error):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="assign",
                actor_id=scope.client_id,
                operation_key="invalid",
                expected_version=0,
                due_at=clock.at + timedelta(days=1),
                terms_reference="terms",
            ),
        )
    assert not repo.events


@pytest.mark.asyncio
async def test_caller_rollback_keeps_state_events_notices_and_outbox_atomic():
    service, repo, scope, _, Command, _, current = await started()
    with pytest.raises(RuntimeError, match="commit failed"):
        async with repo.transaction() as session:
            await service.execute(
                Command(
                    assignment_id=scope.assignment_id,
                    action="claim",
                    actor_id=scope.creator_id,
                    operation_key="rollback",
                    expected_version=current.version,
                    evidence="proof",
                ),
                session=session,
            )
            raise RuntimeError("commit failed")
    assert len(repo.events) == 2
    assert not repo.notices
    assert len(repo.outbox) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,error",
    [
        ({"action": "grant_money"}, "unsupported_collaboration_command"),
        ({"operation_key": " "}, "command_key_required"),
        ({"operation_key": " " + "x" * 199 + " "}, "command_key_required"),
        ({"expected_version": True}, "collaboration_version_required"),
        ({"expected_version": 5}, "collaboration_version_conflict"),
        ({"assignment_id": None}, "assignment_identity_required"),
        ({"actor_id": None}, "authenticated_actor_required"),
        ({"system_actor": "made_up"}, "ambiguous_actor"),
        ({"terms_reference": None}, "agreed_terms_required"),
        ({"action": "start"}, "collaboration_not_found"),
    ],
)
async def test_command_validation_does_not_persist_partial_facts(
    changes, error
):
    service, repo, scope, clock, Command, _ = setup_lifecycle()
    cmd = Command(
        assignment_id=scope.assignment_id,
        action="assign",
        actor_id=scope.client_id,
        operation_key="invalid",
        expected_version=0,
        due_at=clock.at + timedelta(days=1),
        terms_reference="terms",
    )
    with pytest.raises((PermissionError, ValueError), match=error):
        await execute(service, repo, replace(cmd, **changes))
    assert not repo.events
    assert not repo.records


@pytest.mark.asyncio
async def test_actor_current_profile_and_status_are_required():
    service, repo, scope, clock, Command, _ = setup_lifecycle()
    cmd = Command(
        assignment_id=scope.assignment_id,
        action="assign",
        actor_id=scope.client_id,
        operation_key="role",
        expected_version=0,
        due_at=clock.at + timedelta(days=1),
        terms_reference="terms",
    )
    actor = repo.actors[scope.client_id]
    for change, error in (
        ({"status": "blocked"}, "active_actor_required"),
        ({"is_client": False}, "client_consent_required"),
    ):
        repo.actors[scope.client_id] = replace(actor, **change)
        with pytest.raises(PermissionError, match=error):
            await execute(service, repo, cmd)
    repo.actors.pop(scope.client_id)
    with pytest.raises(PermissionError, match="active_actor_required"):
        await execute(service, repo, cmd)


@pytest.mark.asyncio
async def test_changed_scope_old_clock_and_duplicate_assignment_are_refused():
    service, repo, scope, clock, Command, _, current = await started()
    cmd = Command(
        assignment_id=scope.assignment_id,
        action="claim",
        actor_id=scope.creator_id,
        operation_key="scope",
        expected_version=2,
        evidence="proof",
    )
    repo.scopes[scope.assignment_id] = replace(scope, manager_id=None)
    with pytest.raises(ValueError, match="collaboration_scope_changed"):
        await execute(service, repo, cmd)
    repo.scopes[scope.assignment_id] = scope
    clock.at -= timedelta(minutes=10)
    with pytest.raises(ValueError, match="collaboration_time_conflict"):
        await execute(service, repo, cmd)
    clock.at -= timedelta(days=1)
    with pytest.raises(ValueError, match="collaboration_time_conflict"):
        await execute(service, repo, cmd)
    clock.at += timedelta(days=2)
    with pytest.raises(ValueError, match="collaboration_already_assigned"):
        await execute(
            service,
            repo,
            replace(
                cmd,
                action="assign",
                actor_id=scope.client_id,
                due_at=clock.at + timedelta(days=1),
                terms_reference="terms",
            ),
        )
    repo.scopes[scope.assignment_id] = replace(
        scope, client_id=scope.creator_id
    )
    with pytest.raises(
        ValueError, match="distinct_collaboration_parties_required"
    ):
        await execute(service, repo, cmd)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,error",
    [
        (
            {"system_actor": "pretend"},
            "trusted_collaboration_producer_required",
        ),
        ({"accepted": None}, "notice_result_required"),
        ({"external_reference": " "}, "notice_reference_or_error_required"),
        ({"notice_id": None}, "objection_notice_required"),
        ({"notice_id": uuid4()}, "objection_notice_required"),
    ],
)
async def test_transport_requires_real_notice_and_accepted_reference(
    changes, error
):
    service, repo, scope, _, Command, _, current = await claimed()
    notice = next(iter(repo.notices.values()))
    cmd = system_command(
        Command,
        scope,
        current,
        "notice",
        "invalid-notice",
        notice_id=notice.notice_id,
        accepted=True,
        channel="telegram",
        external_reference="message:1",
    )
    with pytest.raises((PermissionError, ValueError), match=error):
        await execute(service, repo, replace(cmd, **changes))
    assert len(repo.events) == 3


@pytest.mark.asyncio
async def test_unconsented_extension_and_late_request_are_refused():
    service, repo, scope, clock, Command, _, current = await started()
    with pytest.raises(
        ValueError, match="extension_consent_and_reason_required"
    ):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="extend_due",
                operation_key="unagreed",
                expected_version=current.version,
                actor_id=scope.client_id,
                expected_due_version=1,
                due_at=clock.at + timedelta(days=7),
            ),
        )
    clock.at += timedelta(days=16)
    with pytest.raises(ValueError, match="confirmation_request_state_conflict"):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="request_confirmation",
                operation_key="too-late",
                expected_version=current.version,
                actor_id=scope.manager_id,
            ),
        )


@pytest.mark.asyncio
async def test_memory_repository_requires_live_caller_transaction():
    _, repo, _, clock, _, _ = setup_lifecycle()
    with pytest.raises(ValueError, match="caller_transaction_required"):
        await repo.get(uuid4(), session=None)
    async with repo.transaction() as session:
        with pytest.raises(ValueError, match="assignment_not_found"):
            await repo.lock_scope(uuid4(), session=session)
        with pytest.raises(ValueError, match="invalid_batch_limit"):
            await repo.list_due(clock.at, 0, session=session)


@pytest.mark.asyncio
async def test_same_due_in_another_timezone_replays_the_original_agreement():
    service, repo, scope, clock, Command, _ = setup_lifecycle()
    command = Command(
        assignment_id=scope.assignment_id,
        action="assign",
        actor_id=scope.client_id,
        operation_key="timezone-replay",
        expected_version=0,
        due_at=clock.at + timedelta(days=1),
        terms_reference="terms:1",
    )
    first = await execute(service, repo, command)
    shifted = command.due_at.astimezone(timezone(timedelta(hours=3)))
    assert (
        await execute(service, repo, replace(command, due_at=shifted)) == first
    )


@pytest.mark.asyncio
async def test_private_status_allows_parties_and_current_assigned_manager():
    service, repo, scope, _, _, stranger, current = await started()
    for actor in (scope.client_id, scope.creator_id, scope.manager_id):
        async with repo.transaction() as session:
            result = await service.get_for_actor(
                scope.assignment_id, actor, session=session
            )
        assert result == current
    async with repo.transaction() as session:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_for_actor(
                scope.assignment_id, stranger, session=session
            )
    assert len(repo.events) == 2


@pytest.mark.asyncio
async def test_historical_status_remains_private_after_replacement():
    service, repo, scope, clock, _, _, current = await started()
    repo.scopes[scope.assignment_id] = replace(scope, valid_to=clock.at)
    for actor in (scope.client_id, scope.creator_id):
        async with repo.transaction() as session:
            assert (
                await service.get_for_actor(
                    scope.assignment_id, actor, session=session
                )
                == current
            )
    async with repo.transaction() as session:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_for_actor(
                scope.assignment_id, scope.manager_id, session=session
            )


@pytest.mark.asyncio
async def test_status_rechecks_current_profile_status_and_manager_membership():
    service, repo, scope, _, _, _, _ = await started()
    client = repo.actors[scope.client_id]
    repo.actors[scope.client_id] = replace(client, is_client=False)
    async with repo.transaction() as session:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_for_actor(
                scope.assignment_id, scope.client_id, session=session
            )
    repo.actors[scope.client_id] = replace(client, status="blocked")
    repo.actors[scope.manager_id] = replace(
        repo.actors[scope.manager_id], manager_order_ids=()
    )
    async with repo.transaction() as session:
        with pytest.raises(PermissionError, match="active_actor_required"):
            await service.get_for_actor(
                scope.assignment_id, scope.client_id, session=session
            )
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_for_actor(
                scope.assignment_id, scope.manager_id, session=session
            )
        assert (
            await service.get_for_actor(
                uuid4(), scope.creator_id, session=session
            )
            is None
        )


@pytest.mark.asyncio
async def test_timer_batch_excludes_closed_historical_assignment():
    _, repo, scope, clock, _, _, _ = await started()
    repo.scopes[scope.assignment_id] = replace(scope, valid_to=clock.at)
    clock.at += timedelta(days=20)
    async with repo.transaction() as session:
        assert await repo.list_due(clock.at, 1, session=session) == ()
