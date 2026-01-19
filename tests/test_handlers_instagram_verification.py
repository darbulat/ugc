"""Tests for Instagram verification handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.instagram_verification import (
    InstagramVerificationStates,
    sent_code,
    start_verification,
    verify_code,
)
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

    async def update_data(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._data.update(kwargs)

    async def set_state(self, state) -> None:  # type: ignore[no-untyped-def]
        self.state = state

    async def get_data(self) -> dict:  # type: ignore[no-untyped-def]
        return dict(self._data)

    async def clear(self) -> None:
        self._data.clear()
        self.state = None


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


@pytest.mark.asyncio
async def test_start_verification_requires_role() -> None:
    """Require blogger role before verification."""

    repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_service = UserRoleService(user_repo=repo)
    verification_service = InstagramVerificationService(
        user_repo=repo,
        blogger_repo=blogger_repo,
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_verification(
        message, state, user_service, profile_service, verification_service
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
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(3, "user", "User"))
    state = FakeFSMContext()

    await start_verification(
        message, state, user_service, profile_service, verification_service
    )

    assert message.answers
    assert "Профиль блогера не заполнен" in message.answers[0]


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
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(4, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_verification(
        message, state, user_service, profile_service, verification_service
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
        verification_repo=InMemoryInstagramVerificationRepository(),
    )
    profile_service = _profile_service(user_repo, blogger_repo)
    message = FakeMessage(text=None, user=FakeUser(5, "paused", "Paused"))
    state = FakeFSMContext()

    await start_verification(
        message, state, user_service, profile_service, verification_service
    )

    assert message.answers
    assert "паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_sent_code_moves_state() -> None:
    """Move to waiting_code state."""

    message = FakeMessage(text="Я отправил код", user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    await sent_code(message, state)

    assert state.state == InstagramVerificationStates.waiting_code


@pytest.mark.asyncio
async def test_verify_code_empty() -> None:
    """Reject empty code."""

    message = FakeMessage(text=" ", user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    await state.update_data(user_id="id", attempts=0)

    service = InstagramVerificationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        verification_repo=InMemoryInstagramVerificationRepository(),
    )

    await verify_code(message, state, service)
    assert "Код не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_verify_code_success_flow() -> None:
    """Verify code successfully."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=verification_repo,
    )

    user = user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
    )
    blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=False,
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )
    verification = verification_service.generate_code(user.user_id)

    message = FakeMessage(text=verification.code, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id, attempts=0)

    await verify_code(message, state, verification_service)
    assert "Instagram подтверждён" in message.answers[-1]


@pytest.mark.asyncio
async def test_verify_code_attempts_regen() -> None:
    """Regenerate code after three attempts."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    verification_repo = InMemoryInstagramVerificationRepository()
    user_service = UserRoleService(user_repo=user_repo)
    verification_service = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=verification_repo,
    )

    user = user_service.set_user(
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
    )
    blogger_repo.save(
        BloggerProfile(
            user_id=user.user_id,
            instagram_url="https://instagram.com/test_user",
            confirmed=False,
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    message = FakeMessage(text="WRONG", user=FakeUser(2, "user", "User"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id, attempts=2)

    await verify_code(message, state, verification_service)
    assert "Генерируем новый код" in message.answers[-2]
