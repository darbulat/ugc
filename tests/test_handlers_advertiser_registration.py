"""Tests for advertiser registration handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    handle_contact,
    start_advertiser_registration,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
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


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user() -> None:
    """Require existing user before registration."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state() -> None:
    """Start registration for advertiser role."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert state._data["user_id"] is not None
    assert state.state is not None


@pytest.mark.asyncio
async def test_start_advertiser_registration_blocked_user() -> None:
    """Reject registration for blocked advertiser."""

    repo = InMemoryUserRepository()
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000720"),
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(blocked_user)
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(11, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_start_advertiser_registration_paused_user() -> None:
    """Reject registration for paused advertiser."""

    repo = InMemoryUserRepository()
    paused_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000721"),
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="paused",
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(paused_user)
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(12, "paused", "Paused"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    assert "паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_requires_value() -> None:
    """Require non-empty contact."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    advertiser_service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    await handle_contact(message, state, advertiser_service)
    assert message.answers
    assert "Контакт не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_success() -> None:
    """Store contact and create profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_service = UserRoleService(user_repo=user_repo)
    advertiser_service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
    )
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="@contact", user=FakeUser(20, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_contact(message, state, advertiser_service)

    assert message.answers
    assert "Профиль рекламодателя создан" in message.answers[0]
    profile = await advertiser_repo.get_by_user_id(user.user_id)
    assert profile is not None
