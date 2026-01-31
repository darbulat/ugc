"""Tests for role reminder scheduler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository
from ugc_bot.role_reminder_scheduler import _reminder_cutoff, run_once


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
    """run_once sends reminder to pending user and updates last_role_reminder_at."""

    repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        external_id="123",
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

    with patch(
        "ugc_bot.role_reminder_scheduler.send_with_retry",
        new_callable=AsyncMock,
    ) as mock_send:
        await run_once(bot, service, cutoff)

        mock_send.assert_called_once()
        assert mock_send.call_args[1]["chat_id"] == 123
        updated = await service.get_user_by_id(user.user_id)
        assert updated is not None
        assert updated.last_role_reminder_at is not None


@pytest.mark.asyncio
async def test_run_once_skips_non_telegram_messenger(fake_tm) -> None:
    """run_once only processes telegram users (external_id is digit)."""

    repo = InMemoryUserRepository()
    user = User(
        user_id=uuid4(),
        external_id="non_digit",
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

    with patch(
        "ugc_bot.role_reminder_scheduler.send_with_retry",
        new_callable=AsyncMock,
    ) as mock_send:
        await run_once(bot, service, cutoff)
        mock_send.assert_not_called()


def test_main_disabled_exits_early() -> None:
    """main() exits without sending when role_reminder is disabled."""

    with patch("ugc_bot.role_reminder_scheduler.load_config") as mock_load:
        config = MagicMock()
        config.role_reminder.role_reminder_enabled = False
        mock_load.return_value = config
        with patch("ugc_bot.role_reminder_scheduler.configure_logging"):
            with patch("ugc_bot.role_reminder_scheduler.log_startup_info"):
                from ugc_bot.role_reminder_scheduler import main

                main()
                mock_load.assert_called_once()
