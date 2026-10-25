"""Lead transport construction is default off and owns no caller resources."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.unit.test_notice_delivery_container import config
from ugc_bot.container import Container
from ugc_bot.infrastructure.messenger import notice_receipts


def test_lead_worker_disabled_before_repository_or_transport(monkeypatch):
    container = Container(config())
    monkeypatch.setattr(
        container, "build_repos", Mock(side_effect=AssertionError)
    )
    assert container.build_accompaniment_lead_delivery(object()) is None


def test_lead_factory_uses_caller_bot_session_and_real_sql_repo():
    from ugc_bot.infrastructure.db.repositories import (
        accompaniment_lead_delivery as lead_repo,
    )

    container = Container(config(enabled=True, max_token="synthetic-token"))
    bot, session = object(), object()
    worker = container.build_accompaniment_lead_delivery(
        bot, max_session=session
    )
    assert isinstance(
        worker.repository,
        lead_repo.SqlAlchemyAccompanimentLeadDeliveryRepository,
    )
    assert worker.transactions is container.transaction_manager
    assert isinstance(worker.transport, notice_receipts.RoutedNoticeReceipts)
    assert worker.transport.transports["telegram"].bot is bot
    assert worker.transport.transports["max"].session is session
    assert worker.clock.now().tzinfo is not None
    missing = Container(config(enabled=True, database=""))
    with pytest.raises(ValueError, match="DATABASE_URL"):
        missing.build_accompaniment_lead_delivery(bot)


@pytest.mark.asyncio
async def test_lead_runtime_default_off_has_no_side_effects(monkeypatch):
    from ugc_bot import accompaniment_lead_scheduler as scheduler

    monkeypatch.setattr(
        scheduler.aiohttp, "ClientSession", Mock(side_effect=AssertionError)
    )
    container = Mock()
    await scheduler.run_enabled(config(), container, object(), max_iterations=1)
    assert not container.mock_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_lead_runtime_closes_owned_max_and_preserves_caller_bot(
    monkeypatch, cancel
):
    from ugc_bot import accompaniment_lead_scheduler as scheduler

    entered = asyncio.Event()
    closed = []
    session = object()

    class Session:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            closed.append(True)

    monkeypatch.setattr(scheduler.aiohttp, "ClientSession", Session)

    async def once():
        entered.set()
        if cancel:
            await asyncio.Future()
        return 0

    container = SimpleNamespace(
        build_accompaniment_lead_delivery=Mock(
            return_value=SimpleNamespace(run_once=once)
        )
    )
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    task = asyncio.create_task(
        scheduler.run_enabled(
            config(enabled=True, max_token="synthetic-token"),
            container,
            bot,
            max_iterations=1,
        )
    )
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert closed == [True]
    bot.session.close.assert_not_awaited()
    container.build_accompaniment_lead_delivery.assert_called_once_with(
        bot, max_session=session
    )


@pytest.mark.asyncio
async def test_lead_loop_recovers_database_error_without_sensitive_logs(
    monkeypatch, caplog
):
    from ugc_bot import accompaniment_lead_scheduler as scheduler

    worker = SimpleNamespace(
        run_once=AsyncMock(side_effect=[RuntimeError("secret payload"), 0])
    )
    monkeypatch.setattr(scheduler.asyncio, "sleep", AsyncMock())
    await scheduler.run_loop(worker, interval_seconds=3, max_iterations=2)
    assert worker.run_once.await_count == 2
    assert "secret payload" not in caplog.text
    with pytest.raises(ValueError, match="lead_loop"):
        await scheduler.run_loop(worker, interval_seconds=0)


@pytest.mark.asyncio
async def test_combined_runtime_starts_dedicated_lead_owner(monkeypatch):
    from ugc_bot import combined_scheduler

    async def empty(*args):
        return None

    started = []

    async def lead(config, container, bot):
        started.append((config, container, bot))

    monkeypatch.setattr(combined_scheduler, "collaboration_loop", empty)
    monkeypatch.setattr(combined_scheduler, "notice_loop", empty)
    monkeypatch.setattr(combined_scheduler, "selection_maturity_loop", empty)
    monkeypatch.setattr(combined_scheduler, "manual_grant_loop", empty)
    monkeypatch.setattr(combined_scheduler, "lead_loop", lead, raising=False)
    current = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True),
        feedback=SimpleNamespace(feedback_enabled=False),
        role_reminder=SimpleNamespace(role_reminder_enabled=False),
        referral=SimpleNamespace(referral_reconciliation_enabled=False),
    )
    container = SimpleNamespace(
        build_collaboration_sweep=lambda: object(),
        build_selection_maturity_sweep=lambda: object(),
        build_manual_grant_sweep=lambda: object(),
    )
    bot = object()
    await combined_scheduler._run_all(current, container, bot)
    assert started == [(current, container, bot)]


@pytest.mark.parametrize("lease", [0, -1, True])
def test_invalid_lease_rejected_before_any_repository_calls(lease):
    from ugc_bot.application.services.accompaniment_lead_delivery import (
        AccompanimentLeadDelivery,
    )

    with pytest.raises(ValueError, match="lead_lease_invalid"):
        AccompanimentLeadDelivery(None, None, None, None, lease_seconds=lease)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, 1001])
async def test_invalid_batch_rejected_before_any_repository_calls(limit):
    from ugc_bot.application.services.accompaniment_lead_delivery import (
        AccompanimentLeadDelivery,
    )

    worker = AccompanimentLeadDelivery(None, None, None, None)
    with pytest.raises(ValueError, match="lead_batch_invalid"):
        await worker.run_once(limit)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,key",
    [
        ("", "review"),
        ("review", ""),
        ("x" * 4001, "review"),
        ("review", "x" * 257),
    ],
)
async def test_review_requires_reason_and_bounded_key_before_database(
    reason, key
):
    from uuid import uuid4

    from ugc_bot.application.services.accompaniment_lead_delivery import (
        AccompanimentLeadDelivery,
    )

    worker = AccompanimentLeadDelivery(None, None, None, None)
    with pytest.raises(ValueError, match="lead_retry_provenance_required"):
        await worker.retry(
            uuid4(), actor_id=uuid4(), reason=reason, operation_key=key
        )
