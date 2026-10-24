"""Due transitions run through the persisted command and caller transaction."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.application.services.test_collaboration_service import (
    execute,
    setup_lifecycle,
    started,
)
from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.domain.collaboration import CollaborationState


def sweep(service, repo):
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )

    return CollaborationSweepService(service, repo)


@pytest.mark.asyncio
async def test_both_silent_expire_once_through_durable_command():
    service, repo, scope, clock, Command, _ = setup_lifecycle()
    await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="assign",
            actor_id=scope.client_id,
            operation_key="assign",
            expected_version=0,
            due_at=clock.at + timedelta(days=2),
            terms_reference="agreed brief",
        ),
    )
    worker = sweep(service, repo)
    clock.at += timedelta(days=16)
    result = await worker.run_once()
    assert result.changed == 1
    assert result.rejected == 0
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == CollaborationState.UNCONFIRMED_EXPIRED
    )
    assert not repo.schedules
    assert (await worker.run_once()).attempted == 0
    assert len(repo.events) == 2


@pytest.mark.asyncio
async def test_accepted_notice_finalizes_at_72h_then_waits_full_hold():
    service, repo, scope, clock, _, _, current = await started()
    await execute(
        service,
        repo,
        CollaborationCommand(
            assignment_id=scope.assignment_id,
            action="claim",
            actor_id=scope.creator_id,
            operation_key="claim",
            expected_version=current.version,
            evidence="proof",
        ),
    )
    notice = next(iter(repo.notices.values()))
    await execute(
        service,
        repo,
        CollaborationCommand(
            assignment_id=scope.assignment_id,
            action="notice",
            system_actor="collaboration_notifier",
            operation_key="notice",
            expected_version=3,
            notice_id=notice.notice_id,
            accepted=True,
            channel="telegram",
            external_reference="actual-receipt:1",
        ),
    )
    worker = sweep(service, repo)
    clock.at += timedelta(hours=72)
    assert (await worker.run_once()).changed == 1
    work = repo.records[scope.assignment_id].collaboration
    assert work.state == CollaborationState.SUCCESS_FINAL
    assert work.success_final_at == clock.at
    assert (await worker.run_once()).attempted == 0
    clock.at += timedelta(days=14)
    assert (await worker.run_once()).changed == 1
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == CollaborationState.AVAILABLE
    )
    assert len(repo.schedules) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_missing_or_failed_notice_never_auto_finalizes(failed):
    service, repo, scope, clock, _, _, current = await started()
    await execute(
        service,
        repo,
        CollaborationCommand(
            assignment_id=scope.assignment_id,
            action="claim",
            actor_id=scope.creator_id,
            operation_key="claim",
            expected_version=current.version,
            evidence="proof",
        ),
    )
    if failed:
        notice = next(iter(repo.notices.values()))
        await execute(
            service,
            repo,
            CollaborationCommand(
                assignment_id=scope.assignment_id,
                action="notice",
                system_actor="collaboration_notifier",
                operation_key="failed-notice",
                expected_version=3,
                notice_id=notice.notice_id,
                accepted=False,
                channel="telegram",
                reason="transport failed",
            ),
        )
    clock.at += timedelta(days=30)
    assert (await sweep(service, repo).run_once()).attempted == 0
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == CollaborationState.SUCCESS_CLAIMED
    )
    assert not repo.schedules


@pytest.mark.asyncio
async def test_replaced_historical_assignment_does_not_starve_due_batch():
    service, repo, scope, clock, _, _, _ = await started()
    repo.scopes[scope.assignment_id] = replace(scope, valid_to=clock.at)
    clock.at += timedelta(days=30)
    assert (await sweep(service, repo).run_once()).attempted == 0


@pytest.mark.asyncio
async def test_racing_user_change_rejects_stale_candidate_without_overwrite():
    service, repo, scope, clock, _, _, _ = await started()
    clock.at += timedelta(days=16)
    original = repo.list_due

    async def changed_after_discovery(at, limit, *, session):
        records = await original(at, limit, session=session)
        # Model another committed command by returning a stale version snapshot.
        return tuple(
            replace(record, version=record.version - 1) for record in records
        )

    repo.list_due = changed_after_discovery
    result = await sweep(service, repo).run_once()
    assert result.attempted == 1
    assert result.changed == 0
    assert result.rejected == 1
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == CollaborationState.IN_PROGRESS
    )
