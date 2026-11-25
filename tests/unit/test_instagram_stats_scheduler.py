"""Tests for Instagram stats scheduler."""

from asyncio import CancelledError
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot import instagram_stats_scheduler as scheduler
from ugc_bot.application.services.instagram_stats_update_service import (
    InstagramStatsUpdateService,
)
from ugc_bot.instagram_stats_scheduler import run_loop, run_once


@pytest.mark.asyncio
async def test_run_once_calls_service_run_once() -> None:
    """run_once delegates to service.run_once."""
    updated, errors = 2, 0
    service = MagicMock(spec=InstagramStatsUpdateService)
    service.run_once = AsyncMock(return_value=(updated, errors))

    await run_once(service)

    service.run_once.assert_called_once()


@pytest.mark.asyncio
async def test_run_loop_stops_after_max_iterations() -> None:
    """run_loop stops when max_iterations reached."""
    service = MagicMock(spec=InstagramStatsUpdateService)
    service.run_once = AsyncMock(return_value=(0, 0))

    await run_loop(
        service,
        interval_seconds=0,
        max_iterations=2,
    )

    assert service.run_once.call_count == 2


@pytest.mark.asyncio
async def test_offer_checks_poll_again_after_a_failed_batch(
    monkeypatch, caplog
):
    checker = SimpleNamespace(
        run_once=AsyncMock(side_effect=[RuntimeError("synthetic"), None])
    )
    sleep = AsyncMock(side_effect=[None, CancelledError()])
    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)

    with pytest.raises(CancelledError):
        await scheduler._check_confirmed_offers(checker)

    assert checker.run_once.await_count == 2
    assert [call.args for call in sleep.await_args_list] == [(60,), (60,)]
    assert "Instagram offer check batch failed (RuntimeError)" in caplog.text
