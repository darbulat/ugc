"""The real notice run loop is gated, bounded and closes owned MAX resources."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.application.services.test_collaboration_notice_delivery import (
    setup_delivery,
)


def scheduler():
    try:
        from ugc_bot import notice_delivery_scheduler
    except ImportError:
        pytest.fail("Notice runtime loop is missing")
    return notice_delivery_scheduler


@pytest.mark.asyncio
async def test_notice_loop_executes_real_lifecycle_then_never_resends():
    module = scheduler()
    worker, _, repo, scope, _, _, _, transport = await setup_delivery()
    await module.run_loop(worker, max_iterations=1)
    await module.run_loop(worker, max_iterations=1)
    assert len(transport.sent) == 1
    assert (
        repo.records[scope.assignment_id].collaboration.notice_delivered_at
        is not None
    )


@pytest.mark.asyncio
async def test_loop_retries_db_failure_without_logging_sensitive_body(
    monkeypatch, caplog
):
    module = scheduler()
    worker = SimpleNamespace(
        run_once=AsyncMock(
            side_effect=[RuntimeError("sensitive query payload"), 0]
        )
    )
    delay = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", delay)
    await module.run_loop(worker, interval_seconds=17, max_iterations=2)
    assert worker.run_once.await_count == 2
    delay.assert_awaited_once_with(17)
    assert "notice" in caplog.text.lower()
    assert "sensitive query payload" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("interval,iterations", [(0, 1), (-1, 1), (1, 0)])
async def test_invalid_loop_bounds_fail_before_processing(interval, iterations):
    module = scheduler()
    worker = SimpleNamespace(run_once=AsyncMock())
    with pytest.raises(ValueError, match="notice_loop"):
        await module.run_loop(
            worker, interval_seconds=interval, max_iterations=iterations
        )
    worker.run_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_runtime_constructs_no_transport_session_or_worker(
    monkeypatch,
):
    module = scheduler()
    monkeypatch.setattr(
        module.aiohttp,
        "ClientSession",
        Mock(side_effect=AssertionError("disabled session construction")),
    )
    container = Mock()
    config = SimpleNamespace(financial=SimpleNamespace(core_enabled=False))
    await module.run_enabled(config, container, object(), max_iterations=1)
    assert not container.mock_calls


@pytest.mark.asyncio
async def test_enabled_runtime_without_max_never_constructs_max_session(
    monkeypatch,
):
    module = scheduler()
    worker, _, _, _, _, _, _, _ = await setup_delivery()
    container = SimpleNamespace(
        build_collaboration_notice_delivery=Mock(return_value=worker)
    )
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True), max_bot=None
    )
    monkeypatch.setattr(
        module.aiohttp,
        "ClientSession",
        Mock(side_effect=AssertionError("missing max capability")),
    )
    bot = object()
    await module.run_enabled(config, container, bot, max_iterations=1)
    container.build_collaboration_notice_delivery.assert_called_once_with(
        bot, max_session=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_max_session_is_closed_on_completion_and_cancellation(
    monkeypatch, cancel
):
    module = scheduler()
    entered = asyncio.Event()
    session = SimpleNamespace(__aenter__=AsyncMock(), __aexit__=AsyncMock())

    class OwnedSession:
        async def __aenter__(self):
            await session.__aenter__()
            return session

        async def __aexit__(self, *args):
            await session.__aexit__(*args)

    make_session = Mock(return_value=OwnedSession())
    monkeypatch.setattr(module.aiohttp, "ClientSession", make_session)

    async def iterate():
        entered.set()
        if cancel:
            await asyncio.Future()
        return 0

    worker = SimpleNamespace(run_once=iterate)
    container = SimpleNamespace(
        build_collaboration_notice_delivery=Mock(return_value=worker)
    )
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True),
        max_bot=SimpleNamespace(token="synthetic-max-token"),
    )
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    task = asyncio.create_task(
        module.run_enabled(config, container, bot, max_iterations=1)
    )
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert session.__aenter__.await_count == session.__aexit__.await_count == 1
    bot.session.close.assert_not_awaited()
    container.build_collaboration_notice_delivery.assert_called_once_with(
        bot, max_session=session
    )


@pytest.mark.asyncio
async def test_combined_core_gate_starts_actual_notice_loop(monkeypatch):
    from ugc_bot import combined_scheduler

    worker, _, repo, scope, _, _, _, transport = await setup_delivery()
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True),
        feedback=SimpleNamespace(feedback_enabled=False),
        role_reminder=SimpleNamespace(role_reminder_enabled=False),
        referral=SimpleNamespace(referral_reconciliation_enabled=False),
        max_bot=None,
    )
    container = SimpleNamespace(
        build_collaboration_sweep=Mock(return_value=object()),
        build_collaboration_notice_delivery=Mock(return_value=worker),
        build_accompaniment_lead_delivery=Mock(return_value=None),
    )

    async def no_deadlines(_):
        return None

    async def one_notice(actual_config, actual_container, bot):
        assert actual_config is config and actual_container is container
        await scheduler().run_enabled(
            actual_config, actual_container, bot, max_iterations=1
        )

    monkeypatch.setattr(combined_scheduler, "collaboration_loop", no_deadlines)
    monkeypatch.setattr(
        combined_scheduler, "notice_loop", one_notice, raising=False
    )

    async def independent_delivery(*_):
        return None

    monkeypatch.setattr(
        combined_scheduler, "selection_loop", independent_delivery
    )
    monkeypatch.setattr(combined_scheduler, "lead_loop", independent_delivery)
    await combined_scheduler._run_all(config, container, object())
    assert len(transport.sent) == 1
    assert (
        repo.records[scope.assignment_id].collaboration.notice_delivered_at
        is not None
    )
