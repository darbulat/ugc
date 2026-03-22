"""Tests for role reminder scheduler."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository
from ugc_bot.role_reminder_scheduler import (
    _reminder_cutoff,
    _seconds_until_next_run,
    run_loop,
    run_once,
)


def test_seconds_until_next_run_before_time_returns_seconds_today() -> None:
    """_seconds_until_next_run when now is before configured time."""
    config = MagicMock()
    config.role_reminder.role_reminder_hour = 23
    config.role_reminder.role_reminder_minute = 30
    config.role_reminder.role_reminder_timezone = "UTC"
    seconds = _seconds_until_next_run(config)
    assert seconds > 0
    assert seconds <= 86400


def test_seconds_until_next_run_after_time_returns_seconds_tomorrow() -> None:
    """_seconds_until_next_run when now is after configured time."""
    config = MagicMock()
    config.role_reminder.role_reminder_hour = 0
    config.role_reminder.role_reminder_minute = 0
    config.role_reminder.role_reminder_timezone = "UTC"
    seconds = _seconds_until_next_run(config)
    assert seconds > 0
    assert seconds <= 86400


def test_reminder_cutoff_returns_utc_datetime() -> None:
    """_reminder_cutoff returns today at configured hour in UTC."""

    config = MagicMock()
    config.role_reminder.role_reminder_hour = 10
    config.role_reminder.role_reminder_minute = 0
    config.role_reminder.role_reminder_timezone = "Europe/Moscow"

    cutoff = _reminder_cutoff(config)

    assert cutoff.tzinfo is not None
    assert cutoff.tzinfo == timezone.utc
    tz = ZoneInfo("Europe/Moscow")
    local = cutoff.astimezone(tz)
    assert local.hour == 10
    assert local.minute == 0


@pytest.mark.asyncio
async def test_run_once_sends_reminder_and_updates_timestamp(fake_tm) -> None:
    """run_once sends reminder to pending user, updates last_role_reminder."""

    from ugc_bot.infrastructure.messenger.telegram.client import (
        TelegramMessengerClient,
    )

    repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        role_chosen_at=None,
        last_role_reminder_at=None,
    )
    await repo.save(user)

    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    cutoff = datetime.now(timezone.utc)
    bot = MagicMock()
    messenger_client = TelegramMessengerClient(bot)

    config = MagicMock()
    config.market = MagicMock()
    config.market.default_locale = "ru"
    with patch(
        "ugc_bot.role_reminder_scheduler.send_with_retry",
        new_callable=AsyncMock,
    ) as mock_send:
        await run_once({"telegram": messenger_client}, service, cutoff, config)

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["chat_id"] == "123"
        updated = await service.get_user_by_id(user.user_id)
        assert updated is not None
        assert updated.last_role_reminder_at is not None


@pytest.mark.asyncio
async def test_run_once_skips_non_telegram_messenger(fake_tm) -> None:
    """run_once only processes telegram users (telegram_id is digit)."""

    from ugc_bot.infrastructure.messenger.telegram.client import (
        TelegramMessengerClient,
    )

    repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="non_digit",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        role_chosen_at=None,
        last_role_reminder_at=None,
    )
    await repo.save(user)

    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    cutoff = datetime.now(timezone.utc)
    bot = MagicMock()
    messenger_client = TelegramMessengerClient(bot)

    config = MagicMock()
    config.market = MagicMock()
    config.market.default_locale = "ru"
    with patch(
        "ugc_bot.role_reminder_scheduler.send_with_retry",
        new_callable=AsyncMock,
    ) as mock_send:
        await run_once({"telegram": messenger_client}, service, cutoff, config)
        mock_send.assert_not_called()


def test_main_disabled_exits_early() -> None:
    """main() exits without sending when role_reminder is disabled."""

    with patch("ugc_bot.role_reminder_scheduler.load_config") as mock_load:
        config = MagicMock()
        config.role_reminder.role_reminder_enabled = False
        mock_load.return_value = config
        with (
            patch("ugc_bot.role_reminder_scheduler.configure_logging"),
            patch("ugc_bot.role_reminder_scheduler.log_startup_info"),
        ):
            from ugc_bot.role_reminder_scheduler import main

            main()
            mock_load.assert_called_once()


def test_main_exits_when_no_database_url() -> None:
    """main() exits when DATABASE_URL is not set."""

    with patch("ugc_bot.role_reminder_scheduler.load_config") as mock_load:
        config = MagicMock()
        config.role_reminder.role_reminder_enabled = True
        config.db.database_url = ""
        mock_load.return_value = config
        with (
            patch("ugc_bot.role_reminder_scheduler.configure_logging"),
            patch("ugc_bot.role_reminder_scheduler.log_startup_info"),
        ):
            from ugc_bot.role_reminder_scheduler import main

            main()
            mock_load.assert_called_once()


@pytest.mark.asyncio
async def test_run_once_handles_send_failure(fake_tm) -> None:
    """On send failure, timestamp already set so no duplicate tomorrow."""

    from ugc_bot.infrastructure.messenger.telegram.client import (
        TelegramMessengerClient,
    )

    repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        telegram_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        role_chosen_at=None,
        last_role_reminder_at=None,
    )
    await repo.save(user)

    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    cutoff = datetime.now(timezone.utc)
    bot = MagicMock()
    messenger_client = TelegramMessengerClient(bot)

    config = MagicMock()
    config.market = MagicMock()
    config.market.default_locale = "ru"
    with patch(
        "ugc_bot.role_reminder_scheduler.send_with_retry",
        new_callable=AsyncMock,
        side_effect=Exception("send failed"),
    ):
        await run_once({"telegram": messenger_client}, service, cutoff, config)

    updated = await service.get_user_by_id(user.user_id)
    assert updated is not None
    assert updated.last_role_reminder_at is not None


@pytest.mark.asyncio
async def test_run_loop_runs_once_then_sleeps(fake_tm) -> None:
    """run_loop calls run_once, then sleeps; one iteration then cancel."""

    from ugc_bot.infrastructure.messenger.telegram.client import (
        TelegramMessengerClient,
    )

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    bot = MagicMock()
    messenger_client = TelegramMessengerClient(bot)
    config = MagicMock()
    config.role_reminder.role_reminder_hour = 12
    config.role_reminder.role_reminder_minute = 0
    config.role_reminder.role_reminder_timezone = "UTC"

    call_count = 0

    async def fake_sleep(secs: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError()

    with (
        patch(
            "ugc_bot.role_reminder_scheduler.send_with_retry",
            new_callable=AsyncMock,
        ),
        patch(
            "ugc_bot.role_reminder_scheduler.asyncio.sleep",
            side_effect=fake_sleep,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_loop({"telegram": messenger_client}, service, config)
    assert call_count == 1
