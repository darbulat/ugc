"""Bounded runtime, owned MAX resources, safe logs and default-off gating."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ugc_bot import paid_selection_delivery_scheduler as module


@pytest.mark.asyncio
@pytest.mark.parametrize("interval,iterations", [(0, 1), (-1, 1), (1, 0)])
async def test_invalid_bounds_never_process(interval, iterations):
    with pytest.raises(
        ValueError, match="selection_delivery_loop_bounds_invalid"
    ):
        await module.run_loop(
            None, interval_seconds=interval, max_iterations=iterations
        )


@pytest.mark.asyncio
async def test_batch_failure_retries_without_sensitive_logging(
    monkeypatch, caplog
):
    worker = SimpleNamespace(
        run_once=AsyncMock(
            side_effect=[RuntimeError("private source payload"), 0]
        )
    )
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await module.run_loop(worker, interval_seconds=17, max_iterations=2)
    assert (
        worker.run_once.await_count == 2
        and "private source payload" not in caplog.text
    )
    sleep.assert_awaited_once_with(17)


@pytest.mark.asyncio
async def test_disabled_runtime_never_constructs_transport_or_session(
    monkeypatch,
):
    config = SimpleNamespace(financial=SimpleNamespace(core_enabled=False))
    container = Mock()
    monkeypatch.setattr(
        module.aiohttp,
        "ClientSession",
        Mock(side_effect=AssertionError("disabled")),
    )
    await module.run_enabled(config, container, object(), max_iterations=1)
    assert not container.mock_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_max_resources_close_on_completion_and_cancellation(
    monkeypatch, cancel
):
    calls, entered = [], asyncio.Event()

    class Owned:
        async def __aenter__(self):
            calls.append("enter")
            return self

        async def __aexit__(self, *args):
            calls.append("exit")

    async def batch():
        entered.set()
        if cancel:
            await asyncio.Future()
        return 0

    worker = SimpleNamespace(run_once=batch)
    container = SimpleNamespace(
        build_paid_selection_delivery=Mock(return_value=worker)
    )
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True),
        max_bot=SimpleNamespace(token="synthetic"),
    )
    monkeypatch.setattr(module.aiohttp, "ClientSession", Owned)
    task = asyncio.create_task(
        module.run_enabled(config, container, object(), max_iterations=1)
    )
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await task
    assert calls == ["enter", "exit"]


@pytest.mark.asyncio
async def test_missing_worker_exits_without_a_loop():
    config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True), max_bot=None
    )
    container = SimpleNamespace(
        build_paid_selection_delivery=Mock(return_value=None)
    )
    await module.run_enabled(config, container, object(), max_iterations=1)
