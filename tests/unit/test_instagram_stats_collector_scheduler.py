"""Tests for Instagram stats collector scheduler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
    RunOnceResult,
)
from ugc_bot.instagram_stats_collector_scheduler import run_loop, run_once


@pytest.mark.asyncio
async def test_run_once_calls_service_run_once() -> None:
    """run_once delegates to service.run_once."""
    service = MagicMock(spec=InstagramStatsCollectorService)
    service.run_once = AsyncMock(
        return_value=RunOnceResult(
            updated=2, errors=0, updated_users=[], failed_users=[]
        )
    )

    await run_once(service)

    service.run_once.assert_called_once()


@pytest.mark.asyncio
async def test_run_loop_stops_after_max_iterations() -> None:
    """run_loop stops when max_iterations reached."""
    service = MagicMock(spec=InstagramStatsCollectorService)
    service.run_once = AsyncMock(
        return_value=RunOnceResult(
            updated=0, errors=0, updated_users=[], failed_users=[]
        )
    )

    await run_loop(
        service,
        interval_seconds=0,
        max_iterations=2,
    )

    assert service.run_once.call_count == 2


@pytest.mark.asyncio
async def test_run_once_logs_updated_and_failed_users() -> None:
    """run_once logs which users were updated and which had problems."""
    service = MagicMock(spec=InstagramStatsCollectorService)
    service.run_once = AsyncMock(
        return_value=RunOnceResult(
            updated=2,
            errors=1,
            updated_users=[
                {"user_id": "u1", "username": "alice"},
                {"user_id": "u2", "username": "bob"},
            ],
            failed_users=[
                {
                    "user_id": "u3",
                    "username": "charlie",
                    "reason": "no_stats_data",
                },
            ],
        )
    )

    with patch(
        "ugc_bot.instagram_stats_collector_scheduler.logger"
    ) as mock_logger:
        await run_once(service)

    mock_logger.info.assert_any_call(
        "Updated Instagram stats for users: %s",
        ["alice", "bob"],
        extra={
            "updated_users": [
                {"user_id": "u1", "username": "alice"},
                {"user_id": "u2", "username": "bob"},
            ],
        },
    )
    mock_logger.warning.assert_any_call(
        "Instagram stats update had problems for %d users: %s",
        1,
        [("charlie", "no_stats_data")],
        extra={
            "failed_users": [
                {
                    "user_id": "u3",
                    "username": "charlie",
                    "reason": "no_stats_data",
                },
            ],
        },
    )


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
