"""Tests for Instagram verification handlers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.instagram_verification import (
    _verification_instruction,
    start_verification,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int, username: str | None, first_name: str) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(self, text: str | None, user: FakeUser | None) -> None:
        self.text = text
        self.from_user = user
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response text."""

        self.answers.append(text)


class FakeFSMContext:
    """Minimal FSM context for tests."""

    def __init__(self) -> None:
        self._data: dict = {}
        self.state = None
        self.cleared = False

    async def update_data(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._data.update(kwargs)

    async def set_state(self, state) -> None:  # type: ignore[no-untyped-def]
        self.state = state

    async def get_data(self) -> dict:  # type: ignore[no-untyped-def]
        return dict(self._data)

    async def clear(self) -> None:
        self._data.clear()
        self.state = None
        self.cleared = True


def _profile_service(
    user_repo: InMemoryUserRepository,
    blogger_repo: InMemoryBloggerProfileRepository,
) -> ProfileService:
    """Build profile service for tests."""

    return ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )


def _fake_config() -> AppConfig:
    """Create a fake config for tests."""
    config = MagicMock(spec=AppConfig)
    config.admin_instagram_username = "admin_ugc_bot"
    return config


@pytest.mark.asyncio
async def test_start_verification_requires_role() -> None:
    """Require blogger role before verification."""

    repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_service = UserRoleService(user_repo=repo)
    verification_service = InstagramVerificationService(
        user_repo=repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(repo, blogger_repo)
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
async def test_start_verification_user_not_found() -> None:
    """Show business error when user is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user_service.set_user(
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
    )
    verification_service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
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
    assert (
        "Instagram URL" in message.answers[0] or "профиль" in message.answers[0].lower()
    )


@pytest.mark.asyncio
async def test_start_verification_already_confirmed() -> None:
    """Skip verification if user already has confirmed Instagram."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000733"),
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    # Create confirmed blogger profile
    blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test",
            confirmed=True,  # Already confirmed
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
    message = FakeMessage(
        text="Пройти верификацию", user=FakeUser(7, "blogger", "Blogger")
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
    assert "уже подтвержден" in message.answers[0]


@pytest.mark.asyncio
async def test_start_verification_blocked_user() -> None:
    """Reject verification for blocked user."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000730"),
        external_id="4",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blocked_user)
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
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
async def test_start_verification_paused_user() -> None:
    """Reject verification for paused user."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    paused_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000731"),
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="paused",
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(paused_user)
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
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
    """Verify instruction text matches TZ requirements."""
    code = "ABC123XY"
    admin_username = "admin_ugc_bot"

    instruction = _verification_instruction(code, admin_username)

    assert "Чтобы подтвердить, что Instagram-аккаунт принадлежит вам" in instruction
    assert "1️⃣ Скопируйте код ниже" in instruction
    assert (
        "2️⃣ Отправьте его в личные сообщения (Direct) Instagram-аккаунта администратора"
        in instruction
    )
    assert "3️⃣ Дождитесь автоматического подтверждения" in instruction
    assert f"Ваш код: {code}" in instruction
    assert f"Admin Instagram: {admin_username}" in instruction
    assert "Код действует 15 минут" in instruction
    assert "запросить новый код" in instruction


@pytest.mark.asyncio
async def test_start_verification_via_button() -> None:
    """Handle verification request via button click."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000732"),
        external_id="6",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    blogger_profile = BloggerProfile(
        user_id=user.user_id,
        instagram_url="https://instagram.com/test",
        confirmed=False,
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    blogger_repo.save(blogger_profile)

    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
    message = FakeMessage(
        text="Пройти верификацию", user=FakeUser(6, "blogger", "Blogger")
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
    assert "Ваш код:" in message.answers[0]
    assert "Admin Instagram:" in message.answers[0]
