"""Tests for advertiser registration handlers."""

import pytest

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    handle_contact,
    start_advertiser_registration,
)
from ugc_bot.domain.enums import MessengerType, UserStatus
from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from tests.helpers.factories import create_test_user


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user(user_repo) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    ans = message.answers[0]
    assert "Пользователь не найден" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state(user_repo) -> None:
    """Start registration for advertiser role."""

    service = UserRoleService(user_repo=user_repo)
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
async def test_start_advertiser_registration_blocked_user(user_repo) -> None:
    """Reject registration for blocked advertiser."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000720"),
        external_id="11",
        username="blocked",
        status=UserStatus.BLOCKED,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(11, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    ans = message.answers[0]
    assert "Заблокированные" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_paused_user(user_repo) -> None:
    """Reject registration for paused advertiser."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000721"),
        external_id="12",
        username="paused",
        status=UserStatus.PAUSE,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(12, "paused", "Paused"))
    state = FakeFSMContext()

    await start_advertiser_registration(message, state, service)

    assert message.answers
    ans = message.answers[0]
    assert "паузе" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_contact_requires_value(user_repo, advertiser_repo) -> None:
    """Require non-empty contact."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    advertiser_service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
    )

    await handle_contact(message, state, advertiser_service)
    assert message.answers
    ans = message.answers[0]
    assert "Контакт не может быть пустым" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_contact_success(user_repo, advertiser_repo) -> None:
    """Store contact and create profile."""

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
    ans = message.answers[0]
    assert "Профиль рекламодателя создан" in (ans if isinstance(ans, str) else ans[0])
    profile = await advertiser_repo.get_by_user_id(user.user_id)
    assert profile is not None
