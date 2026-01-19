"""Tests for blogger registration handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.blogger_registration import (
    handle_agreements,
    handle_age,
    handle_gender,
    handle_geo,
    handle_instagram,
    handle_name,
    handle_price,
    handle_topics,
    start_registration,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
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
async def test_start_registration_requires_blogger_role() -> None:
    """Require blogger role before registration."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_registration(message, state, service)

    assert message.answers
    assert "Please choose role" in message.answers[0]


@pytest.mark.asyncio
async def test_start_registration_sets_state() -> None:
    """Start registration for blogger role."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    service.set_role(
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        role=UserRole.BLOGGER,
    )
    message = FakeMessage(text=None, user=FakeUser(7, "alice", "Alice"))
    state = FakeFSMContext()

    await start_registration(message, state, service)

    assert state._data["external_id"] == "7"
    assert state.state is not None


@pytest.mark.asyncio
async def test_start_registration_blocked_user() -> None:
    """Reject registration for blocked user."""

    repo = InMemoryUserRepository()
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000710"),
        external_id="8",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        role=UserRole.BLOGGER,
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(blocked_user)
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(8, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_registration(message, state, service)

    assert message.answers
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_start_registration_paused_user() -> None:
    """Reject registration for paused user."""

    repo = InMemoryUserRepository()
    paused_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000711"),
        external_id="9",
        messenger_type=MessengerType.TELEGRAM,
        username="paused",
        role=UserRole.BLOGGER,
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(paused_user)
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text=None, user=FakeUser(9, "paused", "Paused"))
    state = FakeFSMContext()

    await start_registration(message, state, service)

    assert message.answers
    assert "паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_instagram_validation_in_handler() -> None:
    """Validate Instagram URL in handler."""

    message = FakeMessage(text="bad_url", user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await handle_instagram(message, state)

    assert message.answers
    assert "Неверный формат" in message.answers[0]


@pytest.mark.asyncio
async def test_instagram_success_in_handler() -> None:
    """Accept valid Instagram URL."""

    message = FakeMessage(
        text="https://instagram.com/test_user",
        user=FakeUser(1, "user", "User"),
    )
    state = FakeFSMContext()

    await handle_instagram(message, state)

    assert state._data["instagram_url"].endswith("test_user")


@pytest.mark.asyncio
async def test_gender_invalid() -> None:
    """Reject invalid gender."""

    message = FakeMessage(text="unknown", user=None)
    state = FakeFSMContext()

    await handle_gender(message, state)

    assert message.answers
    assert "Выберите" in message.answers[0]


@pytest.mark.asyncio
async def test_age_invalid() -> None:
    """Reject invalid age format."""

    message = FakeMessage(text="18", user=None)
    state = FakeFSMContext()

    await handle_age(message, state)

    assert message.answers
    assert "Введите диапазон" in message.answers[0]


@pytest.mark.asyncio
async def test_price_invalid() -> None:
    """Reject invalid price."""

    message = FakeMessage(text="abc", user=None)
    state = FakeFSMContext()

    await handle_price(message, state)

    assert message.answers
    assert "Введите число" in message.answers[0]


@pytest.mark.asyncio
async def test_name_and_topics_flow() -> None:
    """Store nickname and topics."""

    state = FakeFSMContext()
    name_message = FakeMessage(text="Alice", user=FakeUser(1, "user", "User"))
    await handle_name(name_message, state)
    assert state._data["nickname"] == "Alice"

    topics_message = FakeMessage(text="fitness, travel", user=None)
    await handle_topics(topics_message, state)
    assert state._data["topics"]["selected"] == ["fitness", "travel"]


@pytest.mark.asyncio
async def test_name_and_topics_invalid() -> None:
    """Handle invalid name and topics input."""

    state = FakeFSMContext()
    name_message = FakeMessage(text=" ", user=None)
    await handle_name(name_message, state)
    assert "Ник не может" in name_message.answers[0]

    topics_message = FakeMessage(text=" ", user=None)
    await handle_topics(topics_message, state)
    assert "Введите хотя бы одну тему" in topics_message.answers[0]


@pytest.mark.asyncio
async def test_gender_age_geo_price_flow() -> None:
    """Store gender, age, geo, price."""

    state = FakeFSMContext()

    gender_message = FakeMessage(text="все", user=None)
    await handle_gender(gender_message, state)
    assert state._data["audience_gender"] == AudienceGender.ALL

    age_message = FakeMessage(text="18-30", user=None)
    await handle_age(age_message, state)
    assert state._data["audience_age_min"] == 18
    assert state._data["audience_age_max"] == 30

    geo_message = FakeMessage(text="Moscow", user=None)
    await handle_geo(geo_message, state)
    assert state._data["audience_geo"] == "Moscow"

    price_message = FakeMessage(text="1500", user=None)
    await handle_price(price_message, state)
    assert state._data["price"] == 1500.0


@pytest.mark.asyncio
async def test_geo_empty_and_price_negative() -> None:
    """Handle invalid geo and price inputs."""

    state = FakeFSMContext()
    geo_message = FakeMessage(text=" ", user=None)
    await handle_geo(geo_message, state)
    assert "География не может" in geo_message.answers[0]

    price_message = FakeMessage(text="-5", user=None)
    await handle_price(price_message, state)
    assert "Цена должна" in price_message.answers[0]


@pytest.mark.asyncio
async def test_handle_agreements_creates_profile() -> None:
    """Agreement step persists blogger profile."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    user = user_role_service.set_role(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        role=UserRole.BLOGGER,
    )

    message = FakeMessage(text="Согласен", user=FakeUser(42, "bob", "Bob"))
    state = FakeFSMContext()
    await state.update_data(
        user_id=user.user_id,
        external_id="42",
        role=UserRole.BLOGGER,
        nickname="bob",
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
    )

    await handle_agreements(
        message,
        state,
        registration_service,
        user_role_service,
    )

    assert message.answers
    assert "Профиль создан" in message.answers[0]
    assert blogger_repo.get_by_user_id(user.user_id) is not None


@pytest.mark.asyncio
async def test_handle_agreements_requires_consent() -> None:
    """Require explicit consent."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    message = FakeMessage(text="нет", user=FakeUser(1, "bob", "Bob"))
    state = FakeFSMContext()

    await handle_agreements(
        message,
        state,
        registration_service,
        user_role_service,
    )

    assert message.answers
    assert "Нужно согласие" in message.answers[0]
