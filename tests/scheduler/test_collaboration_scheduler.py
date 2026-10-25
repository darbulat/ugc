"""The running deadline loop uses persisted commands and survives a DB retry."""

import asyncio
from datetime import timedelta

import pytest

from tests.application.services.test_collaboration_service import started


@pytest.mark.asyncio
async def test_loop_uses_real_lifecycle_and_returns_after_requested_iteration():
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )
    from ugc_bot.collaboration_scheduler import run_loop

    service, repo, scope, clock, _, _, _ = await started()
    clock.at += timedelta(days=16)
    await run_loop(CollaborationSweepService(service, repo), max_iterations=1)
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == "unconfirmed_expired"
    )


@pytest.mark.asyncio
async def test_loop_recovers_after_transient_failure(monkeypatch, caplog):
    from ugc_bot import collaboration_scheduler
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )

    service, repo, scope, clock, _, _, _ = await started()
    clock.at += timedelta(days=16)
    original = repo.list_due
    attempts = 0

    async def transient(at, limit, *, session):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary SQL outage")
        return await original(at, limit, session=session)

    delays = []

    async def signal_sleep(delay):
        delays.append(delay)

    repo.list_due = transient
    monkeypatch.setattr(asyncio, "sleep", signal_sleep)
    await collaboration_scheduler.run_loop(
        CollaborationSweepService(service, repo),
        interval_seconds=17,
        max_iterations=2,
    )
    assert attempts == 2
    assert delays == [17]
    assert "temporary SQL outage" in caplog.text
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == "unconfirmed_expired"
    )


@pytest.mark.asyncio
async def test_combined_scheduler_starts_enabled_lifecycle_loop(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from ugc_bot import combined_scheduler
    from ugc_bot.application.services.collaboration_sweep_service import (
        CollaborationSweepService,
    )

    service, repo, scope, clock, _, _, _ = await started()
    clock.at += timedelta(days=16)
    worker = CollaborationSweepService(service, repo)
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True),
        feedback=SimpleNamespace(feedback_enabled=False),
        role_reminder=SimpleNamespace(role_reminder_enabled=False),
        referral=SimpleNamespace(referral_reconciliation_enabled=False),
    )
    container = Mock()
    container.build_collaboration_sweep.return_value = worker
    monkeypatch.setattr(
        combined_scheduler, "TelegramMessengerClient", lambda _: object()
    )

    async def one_iteration(actual):
        from ugc_bot.collaboration_scheduler import run_loop

        assert actual is worker
        await run_loop(actual, max_iterations=1)

    monkeypatch.setattr(combined_scheduler, "collaboration_loop", one_iteration)

    async def notices_are_checked_separately(*_):
        return None

    monkeypatch.setattr(
        combined_scheduler, "notice_loop", notices_are_checked_separately
    )

    async def independent_delivery(*_):
        return None

    monkeypatch.setattr(
        combined_scheduler, "selection_loop", independent_delivery
    )
    monkeypatch.setattr(combined_scheduler, "lead_loop", independent_delivery)
    monkeypatch.setattr(
        combined_scheduler, "selection_maturity_loop", independent_delivery
    )
    monkeypatch.setattr(
        combined_scheduler, "manual_grant_loop", independent_delivery
    )
    await combined_scheduler._run_all(config, container, object())
    assert (
        repo.records[scope.assignment_id].collaboration.state
        == "unconfirmed_expired"
    )


@pytest.mark.asyncio
async def test_invalid_loop_interval_is_rejected_before_processing():
    from ugc_bot.collaboration_scheduler import run_loop

    with pytest.raises(ValueError, match="positive_sweep_interval_required"):
        await run_loop(None, interval_seconds=0, max_iterations=1)
