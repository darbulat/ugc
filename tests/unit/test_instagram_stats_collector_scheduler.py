"""Tests for Instagram stats collector scheduler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
)
from ugc_bot.instagram_stats_collector_scheduler import run_loop, run_once


@pytest.mark.asyncio
async def test_run_once_calls_service_run_once() -> None:
    """run_once delegates to service.run_once."""
    updated, errors = 2, 0
    service = MagicMock(spec=InstagramStatsCollectorService)
    service.run_once = AsyncMock(return_value=(updated, errors))

    await run_once(service)

    service.run_once.assert_called_once()


@pytest.mark.asyncio
async def test_run_loop_stops_after_max_iterations() -> None:
    """run_loop stops when max_iterations reached."""
    service = MagicMock(spec=InstagramStatsCollectorService)
    service.run_once = AsyncMock(return_value=(0, 0))

    await run_loop(
        service,
        interval_seconds=0,
        max_iterations=2,
    )

    assert service.run_once.call_count == 2


def test_main_exits_when_stats_collector_disabled() -> None:
    """main() exits when INSTAGRAM_STATS_COLLECTOR_ENABLED is False."""
    from ugc_bot.instagram_stats_collector_scheduler import main

    with patch(
        "ugc_bot.instagram_stats_collector_scheduler.load_config"
    ) as mock_load:
        config = MagicMock()
        config.log.log_level = "INFO"
        config.log.log_format = "json"
        config.instagram.instagram_stats_collector_enabled = False
        config.db.database_url = "postgresql://localhost/db"
        mock_load.return_value = config

        main()

    mock_load.assert_called_once()


def test_main_exits_when_no_database_url() -> None:
    """main() logs error and exits when DATABASE_URL is missing."""
    from ugc_bot.instagram_stats_collector_scheduler import main

    with (
        patch(
            "ugc_bot.instagram_stats_collector_scheduler.load_config"
        ) as mock_load,
        patch("ugc_bot.instagram_stats_collector_scheduler.configure_logging"),
        patch(
            "ugc_bot.instagram_stats_collector_scheduler"
            ".install_exception_hooks"
        ),
        patch("ugc_bot.instagram_stats_collector_scheduler.log_startup_info"),
    ):
        config = MagicMock()
        config.log.log_level = "INFO"
        config.log.log_format = "json"
        config.instagram.instagram_stats_collector_enabled = True
        config.db.database_url = ""
        mock_load.return_value = config

        main()


def test_main_exits_when_no_scrapecreators_key() -> None:
    """main() logs error and exits when SCRAPECREATORS_API_KEY is missing."""
    from ugc_bot.instagram_stats_collector_scheduler import main

    with (
        patch(
            "ugc_bot.instagram_stats_collector_scheduler.load_config"
        ) as mock_load,
        patch("ugc_bot.instagram_stats_collector_scheduler.configure_logging"),
        patch(
            "ugc_bot.instagram_stats_collector_scheduler"
            ".install_exception_hooks"
        ),
        patch("ugc_bot.instagram_stats_collector_scheduler.log_startup_info"),
    ):
        config = MagicMock()
        config.log.log_level = "INFO"
        config.log.log_format = "json"
        config.instagram.instagram_stats_collector_enabled = True
        config.db.database_url = "postgresql://localhost/db"
        config.instagram.scrapecreators_api_key = ""
        mock_load.return_value = config

        main()
