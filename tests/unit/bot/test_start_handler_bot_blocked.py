"""Test that BOT_BLOCKED status is restored to ACTIVE on /start."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingMessage,
    IncomingUser,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.start import _start_command
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


def _make_incoming(external_id: str = "99") -> IncomingMessage:
    return IncomingMessage(
        chat_id=external_id,
        user=IncomingUser(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=None,
        ),
        text="/start",
        message_id=None,
    )


@pytest.mark.asyncio
async def test_bot_blocked_user_restored_to_active_on_start() -> None:
    """User with BOT_BLOCKED status is set to ACTIVE when they send /start."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        telegram_id="99",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked_user",
        status=UserStatus.BOT_BLOCKED,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blocked_user)
    user_role_service = UserRoleService(user_repo=user_repo)

    referral_service = AsyncMock(spec=ReferralService)
    referral_service.parse_referral_code.return_value = None

    messenger_client = AsyncMock()
    state_store = AsyncMock(spec=StateStore)

    role_kb = Keyboard(kind=KeyboardKind.INLINE, rows=[])

    await _start_command(
        incoming=_make_incoming("99"),
        state_store=state_store,
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
        start_text="Welcome",
        role_kb=role_kb,
    )

    updated = await user_repo.get_by_id(blocked_user.user_id)
    assert updated is not None
    assert updated.status == UserStatus.ACTIVE
