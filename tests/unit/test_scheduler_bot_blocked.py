"""Tests: schedulers pass on_bot_blocked callback to send_with_retry."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Interaction, User
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    UserStatus,
)
from ugc_bot.feedback_scheduler import _send_advertiser_feedback
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository
from ugc_bot.role_reminder_scheduler import run_once


def _blocked_client() -> AsyncMock:
    client = AsyncMock()
    client.send_text = AsyncMock(
        side_effect=TelegramForbiddenError(
            method=SendMessage(chat_id=0, text=""),
            message="Forbidden: bot was blocked by the user",
        )
    )
    return client


@pytest.mark.asyncio
async def test_feedback_scheduler_marks_advertiser_bot_blocked() -> None:
    """Advertiser is marked BOT_BLOCKED when feedback send raises Forbidden."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000020"),
        telegram_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    user_role_service = UserRoleService(user_repo=user_repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000021"),
        order_id=UUID("00000000-0000-0000-0000-000000000022"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000023"),
        advertiser_id=advertiser.user_id,
        status=InteractionStatus.OK,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=now,
        updated_at=now,
    )
    messenger_clients = {"telegram": _blocked_client()}

    await _send_advertiser_feedback(
        messenger_clients=messenger_clients,
        interaction=interaction,
        advertiser=advertiser,
        blogger_profile=None,
        texts={},
        user_role_service=user_role_service,
    )

    updated = await user_repo.get_by_id(advertiser.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED


@pytest.mark.asyncio
async def test_role_reminder_scheduler_marks_user_bot_blocked() -> None:
    """User is marked BOT_BLOCKED when role reminder send raises Forbidden."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000030"),
        telegram_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(user)
    user_role_service = UserRoleService(user_repo=user_repo)

    messenger_clients = {"telegram": _blocked_client()}

    config = AsyncMock()
    config.market.start_text = "Start"
    config.market.default_locale = "ru"
    # InMemoryUserRepository returns users with role_chosen_at=None
    # and last_role_reminder_at=None — matches our user.
    await run_once(
        messenger_clients,
        user_role_service,
        reminder_cutoff=now,
        config=config,
    )

    updated = await user_repo.get_by_id(user.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED
