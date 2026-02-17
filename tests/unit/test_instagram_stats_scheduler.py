"""Tests for Instagram stats scheduler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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
