"""Tests for advertiser registration handlers."""

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    handle_advertiser_start,
    handle_brand,
    handle_name,
    handle_phone,
)
from ugc_bot.domain.entities import AdvertiserProfile
from ugc_bot.domain.enums import MessengerType, UserStatus
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
)
from tests.helpers.factories import create_test_user
from tests.helpers.services import build_profile_service


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user(
    user_repo, advertiser_repo
) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "Пользователь не найден" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state(
    user_repo, advertiser_repo
) -> None:
    """Start registration for advertiser role."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert state._data["user_id"] is not None
    assert state.state is not None
    assert message.answers
    first_ans = message.answers[0]
    assert "Как вас зовут" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_start_advertiser_registration_skips_name_when_username_set(
    user_repo, advertiser_repo
) -> None:
    """When user has username, skip name step and ask for phone."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert state._data["user_id"] is not None
    assert state._data["name"] == "adv"
    assert state.state is not None
    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (first_ans if isinstance(first_ans, str) else first_ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_blocked_user(
    user_repo, advertiser_repo
) -> None:
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

    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "Заблокированные" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_paused_user(
    user_repo, advertiser_repo
) -> None:
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

    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "паузе" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_name_requires_value(user_repo, advertiser_repo) -> None:
    """Require non-empty name."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(message, state)
    assert message.answers
    ans = message.answers[0]
    assert "Имя не может быть пустым" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_brand_success(user_repo) -> None:
    """Store brand and ask for site_link."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="My Brand", user=FakeUser(20, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:brand"
    await state.update_data(user_id=user.user_id, name="Test Name", phone="+7900")

    await handle_brand(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "Ссылка на сайт" in (ans if isinstance(ans, str) else ans[0])
    assert state._data.get("brand") == "My Brand"


@pytest.mark.asyncio
async def test_handle_advertiser_start_user_not_found(
    user_repo, advertiser_repo
) -> None:
    """When user not in repo, 'Начать' asks to start with /start."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    message = FakeMessage(text="Начать", user=FakeUser(999, "x", "X"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message, state, user_service, profile_service, FakeFsmDraftService()
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Пользователь не найден" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_handle_advertiser_start_shows_menu_when_profile_exists(
    user_repo, advertiser_repo
) -> None:
    """When advertiser has profile, 'Начать' shows menu."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=user.user_id,
            phone="+7900",
            brand="B",
        )
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    message = FakeMessage(text="Начать", user=FakeUser(30, "adv", "Adv"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message, state, user_service, profile_service, FakeFsmDraftService()
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Выберите действие" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_handle_name_success_asks_phone(user_repo) -> None:
    """Valid name leads to phone prompt."""

    message = FakeMessage(text="Иван", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(message, state)

    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (first_ans if isinstance(first_ans, str) else first_ans[0])
    assert state._data.get("name") == "Иван"


@pytest.mark.asyncio
async def test_handle_phone_success_asks_brand(user_repo) -> None:
    """Valid phone leads to brand prompt."""

    message = FakeMessage(text="+7 900 000-00-00", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"
    await state.update_data(name="Test")

    await handle_phone(message, state)

    assert message.answers
    first_ans = message.answers[0]
    assert "бренда" in (first_ans if isinstance(first_ans, str) else first_ans[0])
    assert state._data.get("phone") == "+7 900 000-00-00"


@pytest.mark.asyncio
async def test_handle_phone_requires_value(user_repo) -> None:
    """Require non-empty phone."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"

    await handle_phone(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "Номер телефона не может быть пустым" in (
        ans if isinstance(ans, str) else ans[0]
    )


@pytest.mark.asyncio
async def test_handle_brand_requires_value(user_repo) -> None:
    """Require non-empty brand."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="40",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=" ", user=FakeUser(40, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:brand"
    await state.update_data(user_id=user.user_id, name="N", phone="+7900")

    await handle_brand(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "Название бренда не может быть пустым" in (
        ans if isinstance(ans, str) else ans[0]
    )
