"""Tests for Instagram verification handlers."""

from unittest.mock import MagicMock

import pytest

from tests.helpers.factories import create_test_user
from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.instagram_verification import (
    _verification_instruction_text,
    start_verification,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType, UserStatus


def _fake_config() -> AppConfig:
    """Create a fake config for tests."""
    config = MagicMock(spec=AppConfig)
    config.instagram = MagicMock()
    config.instagram.admin_instagram_username = "admin_ugc_bot"
    return config


@pytest.mark.asyncio
async def test_start_verification_requires_role(
    user_repo, blogger_repo, instagram_verification_repo
) -> None:
    """Require blogger role before verification."""
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_verification_repo,
    )
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_verification(
        message,
        state,
        user_service,
        profile_service,
        verification_service,
        _fake_config(),
    )

    assert message.answers
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_start_verification_user_not_found(
    user_repo, blogger_repo, instagram_verification_repo
) -> None:
    """Show business error when user is missing."""

    user_service = UserRoleService(user_repo=user_repo)
    await user_service.set_user(
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
    )
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_verification_repo,
    )
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(3, "user", "User"))
    state = FakeFSMContext()

    await start_verification(
        message,
        state,
        user_service,
        profile_service,
        verification_service,
        _fake_config(),
    )

    assert message.answers
    assert "Профиль не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_start_verification_blocked_user(
    user_repo, blogger_repo, instagram_verification_repo
) -> None:
    """Reject verification for blocked user."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000730"),
        external_id="4",
        username="blocked",
        status=UserStatus.BLOCKED,
    )
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_verification_repo,
    )
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(4, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_verification(
        message,
        state,
        user_service,
        profile_service,
        verification_service,
        _fake_config(),
    )

    assert message.answers
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_start_verification_paused_user(
    user_repo, blogger_repo, instagram_verification_repo
) -> None:
    """Reject verification for paused user."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000731"),
        external_id="5",
        username="paused",
        status=UserStatus.PAUSE,
    )
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_verification_repo,
    )
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(5, "paused", "Paused"))
    state = FakeFSMContext()

    await start_verification(
        message,
        state,
        user_service,
        profile_service,
        verification_service,
        _fake_config(),
    )

    assert message.answers
    assert "паузе" in message.answers[0]


def test_verification_instruction_format() -> None:
    """Verify instruction matches TZ (code sent in separate message)."""
    admin_username = "admin_ugc_bot"

    instruction = _verification_instruction_text(admin_username)

    assert "Чтобы подтвердить Instagram" in instruction
    assert "Скопируйте код ниже" in instruction
    assert "Отправьте его в личные сообщения" in instruction
    assert "Instagram" in instruction
    assert admin_username in instruction or "usemycontent" in instruction


@pytest.mark.asyncio
async def test_start_verification_via_button(
    user_repo, blogger_repo, instagram_verification_repo
) -> None:
    """Handle verification request via button click."""
    from datetime import datetime, timezone
    from uuid import UUID

    from ugc_bot.bot.handlers.keyboards import CONFIRM_INSTAGRAM_BUTTON_TEXT
    from ugc_bot.domain.entities import BloggerProfile
    from ugc_bot.domain.enums import AudienceGender, WorkFormat

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000732"),
        external_id="6",
        username="blogger",
    )
    blogger_profile = BloggerProfile(
        user_id=user.user_id,
        instagram_url="https://instagram.com/test",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(blogger_profile)

    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_verification_repo,
    )
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(
        text=CONFIRM_INSTAGRAM_BUTTON_TEXT,
        user=FakeUser(6, "blogger", "Blogger"),
    )
    state = FakeFSMContext()

    await start_verification(
        message,
        state,
        user_service,
        profile_service,
        verification_service,
        _fake_config(),
    )

    assert message.answers
    # First message: instruction (no code)
    assert "Чтобы подтвердить Instagram" in message.answers[0]
    # Second message: code only
    assert len(message.answers) >= 2
    assert len(message.answers[1]) <= 10  # code is short
