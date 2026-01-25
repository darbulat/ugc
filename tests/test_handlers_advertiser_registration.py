"""Tests for advertiser registration handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    handle_contact,
    handle_instagram_url,
    start_advertiser_registration,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


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


def _profile_service(user_repo: InMemoryUserRepository) -> ProfileService:
    """Create profile service for handler tests."""

    return ProfileService(user_repo=user_repo)


def _add_advertiser_profile(
    user_repo: InMemoryUserRepository,
    user_id: UUID,
    instagram_url: str | None = None,
    confirmed: bool = False,
    contact: str = "contact",
) -> None:
    """Seed advertiser profile fields on user."""

    user = user_repo.get_by_id(user_id)
    if user is None:
        return
    user_repo.save(
        User(
            user_id=user.user_id,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            role=UserRole.ADVERTISER,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            instagram_url=instagram_url,
            confirmed=confirmed,
            topics=user.topics,
            audience_gender=user.audience_gender,
            audience_age_min=user.audience_age_min,
            audience_age_max=user.audience_age_max,
            audience_geo=user.audience_geo,
            price=user.price,
            contact=contact,
            profile_updated_at=user.profile_updated_at,
        )
    )


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user() -> None:
    """Require existing user before registration."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

    assert message.answers
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state() -> None:
    """Start registration for advertiser role."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

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
        role=UserRole.ADVERTISER,
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact=None,
        profile_updated_at=None,
    )
    repo.save(blocked_user)
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    message = FakeMessage(text=None, user=FakeUser(11, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

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
        role=UserRole.ADVERTISER,
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact=None,
        profile_updated_at=None,
    )
    repo.save(paused_user)
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    message = FakeMessage(text=None, user=FakeUser(12, "paused", "Paused"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

    assert message.answers
    assert "паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_requires_value() -> None:
    """Require non-empty contact."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    advertiser_service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
    )

    await handle_contact(message, state, advertiser_service)
    assert message.answers
    assert "Контакт не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_success() -> None:
    """Store contact and create profile."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    advertiser_service = AdvertiserRegistrationService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
    )

    message = FakeMessage(text="@contact", user=FakeUser(20, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_contact(message, state, advertiser_service)

    assert message.answers
    assert "Профиль рекламодателя создан" in message.answers[0]
    saved_user = user_repo.get_by_id(user.user_id)
    assert saved_user is not None
    assert saved_user.contact is not None


@pytest.mark.asyncio
async def test_start_advertiser_registration_with_instagram_url() -> None:
    """Skip Instagram URL step if user already has Instagram URL."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000722"),
        external_id="13",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact=None,
        profile_updated_at=None,
    )
    repo.save(user)
    _add_advertiser_profile(
        repo,
        user.user_id,
        instagram_url="https://instagram.com/advertiser",
        confirmed=False,
        contact="test@example.com",
    )
    message = FakeMessage(text=None, user=FakeUser(13, "adv", "Adv"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

    assert state._data["user_id"] is not None
    assert "контактные данные" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_start_advertiser_registration_with_confirmed() -> None:
    """Skip Instagram URL step if user already has confirmed Instagram."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    profile_service = _profile_service(repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000723"),
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact=None,
        profile_updated_at=None,
    )
    repo.save(user)
    _add_advertiser_profile(
        repo,
        user.user_id,
        instagram_url="https://instagram.com/advertiser",
        confirmed=True,
        contact="test@example.com",
    )
    message = FakeMessage(text=None, user=FakeUser(14, "adv", "Adv"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service, profile_service)

    assert state._data["user_id"] is not None
    assert "контактные данные" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_handle_instagram_url_success() -> None:
    """Store Instagram URL and proceed to contact."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(
        text="https://instagram.com/test", user=FakeUser(15, "adv", "Adv")
    )
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_instagram_url(message, state, user_service)

    assert state._data["instagram_url"] == "https://instagram.com/test"
    assert "контактные данные" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_handle_instagram_url_invalid() -> None:
    """Reject invalid Instagram URL."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="16",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text="invalid_url", user=FakeUser(16, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_instagram_url(message, state, user_service)

    assert "корректный Instagram URL" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_instagram_url_empty() -> None:
    """Reject empty Instagram URL."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="17",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text="   ", user=FakeUser(17, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_instagram_url(message, state, user_service)

    assert "не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_exception_handling() -> None:
    """Handle exceptions during advertiser registration."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="18",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    class FailingAdvertiserRegistrationService:
        """Service that raises exceptions."""

        def register_advertiser(self, user_id, contact, instagram_url=None):  # type: ignore[no-untyped-def]
            """Raise exception."""
            from ugc_bot.application.errors import AdvertiserRegistrationError

            raise AdvertiserRegistrationError("Test error")

    message = FakeMessage(text="@contact", user=FakeUser(18, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    failing_service = FailingAdvertiserRegistrationService()
    await handle_contact(message, state, failing_service)

    assert message.answers
    assert "Ошибка регистрации" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_contact_unexpected_exception() -> None:
    """Handle unexpected exceptions during advertiser registration."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    user = user_service.set_user(
        external_id="19",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    class FailingAdvertiserRegistrationService:
        """Service that raises unexpected exceptions."""

        def register_advertiser(self, user_id, contact, instagram_url=None):  # type: ignore[no-untyped-def]
            """Raise unexpected exception."""
            raise RuntimeError("Unexpected error")

    message = FakeMessage(text="@contact", user=FakeUser(19, "adv", "Adv"))
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    failing_service = FailingAdvertiserRegistrationService()
    await handle_contact(message, state, failing_service)

    assert message.answers
    assert "неожиданная ошибка" in message.answers[0]
