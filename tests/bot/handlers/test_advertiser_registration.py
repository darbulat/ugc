"""Tests for advertiser registration handlers."""

from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeCallback,
    FakeContact,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.advertiser_registration import (
    AdvertiserRegistrationStates,
    _advertiser_start_impl,
    handle_advertiser_agreements_callback,
    handle_advertiser_start,
    handle_advertiser_start_callback,
    handle_agreements_confirm,
    handle_brand,
    handle_city,
    handle_company_activity,
    handle_name,
    handle_phone,
    handle_site_link,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_AGREE,
    CALLBACK_ADV_START,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

_TEXTS_RU = DEFAULT_TEXTS["ru"]


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    ans = message.answers[0]
    assert "Пользователь не найден" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state(
    user_repo, advertiser_repo, config, bot_texts_service
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
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
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
    user_repo, advertiser_repo, config, bot_texts_service
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
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert state._data["user_id"] is not None
    assert state._data["name"] == "adv"
    assert state.state is not None
    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_phone_step_sends_phone_prompt(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When asking for phone, message is sent (inline-only: user types)."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) >= 1
    phone_msg = next(
        (s for s in client.sent_text if "телефона" in s["text"]), None
    )
    assert phone_msg is not None
    # Reply keyboard with Share phone button (request_contact)
    keyboard = phone_msg.get("keyboard")
    assert keyboard is not None
    assert keyboard.kind.value == "reply"
    assert len(keyboard.rows) == 1 and len(keyboard.rows[0]) == 1
    assert keyboard.rows[0][0].request_contact is True


@pytest.mark.asyncio
async def test_advertiser_start_callback_starts_flow(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_advertiser_start_callback starts registration via inline."""
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="adv_cb",
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    user = FakeUser(12, "adv_cb", "Adv")
    callback = FakeCallback(
        data=CALLBACK_ADV_START,
        user=user,
        message=FakeMessage(user=user),
    )

    await handle_advertiser_start_callback(
        callback,
        state,
        user_role_service=service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state._data.get("user_id") is not None
    assert state.state is not None
    assert len(client.sent_text) >= 1
    assert any(
        "Как вас зовут" in s["text"] or "телефона" in s["text"]
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_advertiser_agreements_callback_confirms_and_clears(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_advertiser_agreements_callback confirms and shows menu."""
    user = await create_test_user(
        user_repo,
        external_id="13",
        username="adv_agree_cb",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.agreements.state)
    await state.update_data(user_id=user.user_id)
    callback = FakeCallback(
        data=CALLBACK_ADV_AGREE,
        user=FakeUser(13, "adv_agree_cb", "User"),
        message=FakeMessage(user=FakeUser(13, "adv_agree_cb", "User")),
    )

    await handle_advertiser_agreements_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.cleared or state.state is None
    assert len(client.sent_text) >= 1
    assert any(
        "разместить заказ" in s["text"] or "Создать заказ" in s["text"]
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_advertiser_agreements_callback_wrong_state_only_answers(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When state is not agreements, callback only answers."""
    user = await create_test_user(
        user_repo, external_id="14", username="adv_wrong"
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.name.state)
    await state.update_data(user_id=user.user_id)
    callback = FakeCallback(
        data=CALLBACK_ADV_AGREE,
        user=FakeUser(14, "adv_wrong", "User"),
        message=FakeMessage(user=FakeUser(14, "adv_wrong", "User")),
    )

    await handle_advertiser_agreements_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_advertiser_agreements_callback_session_expired(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Agreements callback with no user_id sends session expired."""
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.agreements.state)
    await state.update_data(name="X", phone="+7")
    callback = FakeCallback(
        data=CALLBACK_ADV_AGREE,
        user=FakeUser(60, "adv", "User"),
        message=FakeMessage(user=FakeUser(60, "adv", "User")),
    )

    await handle_advertiser_agreements_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert any("Сессия истекла" in s["text"] for s in client.sent_text)
    assert state.cleared or state._data.get("user_id") is None


@pytest.mark.asyncio
async def test_start_advertiser_registration_blocked_user(
    user_repo, advertiser_repo, config, bot_texts_service
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

    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    ans = message.answers[0]
    assert "Заблокированные" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_paused_user(
    user_repo, advertiser_repo, config, bot_texts_service
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

    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    ans = message.answers[0]
    assert "паузе" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_name_requires_value(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Require non-empty name with min 2 chars."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(
        message, state, config=config, bot_texts_service=bot_texts_service
    )
    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


@pytest.mark.asyncio
async def test_handle_brand_success(
    user_repo, config, bot_texts_service
) -> None:
    """Store brand and ask for company activity."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="My Brand", user=FakeUser(20, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:brand"
    await state.update_data(
        user_id=user.user_id,
        name="Test Name",
        phone="+79001234567",
        city="Казань",
    )

    await handle_brand(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    assert "занимается" in (ans if isinstance(ans, str) else ans[0])
    assert state._data.get("brand") == "My Brand"


@pytest.mark.asyncio
async def test_handle_advertiser_start_user_not_found(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When user not in repo, 'Начать' asks to start with /start."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text="Начать", user=FakeUser(999, "x", "X"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message,
        state,
        user_service,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Пользователь не найден" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_advertiser_start_impl_returns_early_when_user_id_not_uuid(
    user_repo, advertiser_repo
) -> None:
    """_advertiser_start_impl returns early when user_id is not UUID."""
    client = FakeMessengerClient()
    state = FakeFSMContext()
    state_store = AiogramStateStore(state)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    user = FakeUser(1, "u", "U")

    await _advertiser_start_impl(
        chat_id="1",
        state_store=state_store,
        user=user,
        messenger_client=client,
        profile_service=profile_service,
        texts=_TEXTS_RU,
    )

    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_handle_advertiser_start_user_not_found_with_client(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """User not in repo with client/adapter: message sent via client."""
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(text="Начать", user=FakeUser(999, "x", "X"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message,
        state,
        user_service,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Пользователь не найден" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_advertiser_start_shows_menu_when_profile_exists(
    user_repo, advertiser_repo, config, bot_texts_service
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
            phone="+79001234567",
            brand="B",
        )
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text="Начать", user=FakeUser(30, "adv", "Adv"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message,
        state,
        user_service,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Выберите действие" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_handle_name_success_asks_phone(
    user_repo, config, bot_texts_service
) -> None:
    """Valid name leads to phone prompt."""

    message = FakeMessage(text="Иван", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("name") == "Иван"


@pytest.mark.asyncio
async def test_handle_phone_success_asks_city(
    user_repo, config, bot_texts_service
) -> None:
    """Valid phone leads to city prompt."""

    message = FakeMessage(text="89001110777", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"
    await state.update_data(name="Test")

    await handle_phone(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "города" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("phone") == "89001110777"


@pytest.mark.asyncio
async def test_handle_phone_requires_value(
    user_repo, config, bot_texts_service
) -> None:
    """Require non-empty phone."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"

    await handle_phone(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    assert "Номер телефона не может быть пустым" in (
        ans if isinstance(ans, str) else ans[0]
    )


@pytest.mark.asyncio
async def test_handle_phone_with_contact_success_asks_city(
    user_repo, config, bot_texts_service
) -> None:
    """Phone from shared contact is stored; then city prompt is sent."""

    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text=None,
        user=FakeUser(1, "adv", "Adv"),
        contact=FakeContact(phone_number="+79001234567"),
    )
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"
    await state.update_data(name="Test")

    await handle_phone(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state._data.get("phone") == "+79001234567"
    assert any("города" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_city_success_asks_brand(
    user_repo, config, bot_texts_service
) -> None:
    """Valid city leads to brand prompt."""

    message = FakeMessage(text="Казань", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:city"
    await state.update_data(name="Test", phone="+79001234567")

    await handle_city(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "бренда" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("city") == "Казань"


@pytest.mark.asyncio
async def test_handle_city_invalid_sends_error(
    user_repo, config, bot_texts_service
) -> None:
    """handle_city with too long city sends validation error via client."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.city.state)
    await state.update_data(name="Test", phone="+79001234567")
    message = FakeMessage(text="A" * 101, user=FakeUser(1, "adv", "Adv"))

    await handle_city(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Максимум" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_company_activity_success_asks_site_link(
    user_repo, config, bot_texts_service
) -> None:
    """Valid company activity leads to site link prompt."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(
        text="Продажа одежды", user=FakeUser(20, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:company_activity"
    await state.update_data(
        user_id=user.user_id,
        name="Test Name",
        phone="+79001234567",
        city="Казань",
        brand="My Brand",
    )

    await handle_company_activity(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    assert "Ссылка на сайт" in (ans if isinstance(ans, str) else ans[0])
    assert state._data.get("company_activity") == "Продажа одежды"


@pytest.mark.asyncio
async def test_handle_company_activity_invalid_sends_error(
    user_repo, config, bot_texts_service
) -> None:
    """handle_company_activity with too long text sends error via client."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.company_activity.state)
    await state.update_data(
        user_id=user.user_id,
        name="N",
        phone="+79001234567",
        city="City",
        brand="Brand",
    )
    message = FakeMessage(text="A" * 501, user=FakeUser(42, "adv", "Adv"))

    await handle_company_activity(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Максимум" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_brand_requires_value(
    user_repo, config, bot_texts_service
) -> None:
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
    await state.update_data(
        user_id=user.user_id, name="N", phone="+79001234567"
    )

    await handle_brand(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


@pytest.mark.asyncio
async def test_handle_brand_invalid_sends_error(
    user_repo, config, bot_texts_service
) -> None:
    """handle_brand with too short brand sends validation error via client."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="41",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.brand.state)
    await state.update_data(
        user_id=user.user_id, name="N", phone="+79001234567", city="City"
    )
    message = FakeMessage(text="x", user=FakeUser(41, "adv", "Adv"))

    await handle_brand(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("символ" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_name_empty_string(
    user_repo, config, bot_texts_service
) -> None:
    """Reject empty name (empty string after strip)."""
    message = FakeMessage(text="", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


def _test_config() -> AppConfig:
    """Create test config with doc URLs."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///",
            "ADMIN_USERNAME": "a",
            "ADMIN_PASSWORD": "p",
            "ADMIN_SECRET": "s",
            "KAFKA_ENABLED": "false",
            "FEEDBACK_ENABLED": "false",
            "ROLE_REMINDER_ENABLED": "false",
            "REDIS_URL": "redis://",
            "USE_REDIS_STORAGE": "false",
            "DOCS_OFFER_URL": "https://example.com/offer",
            "DOCS_PRIVACY_URL": "https://example.com/privacy",
            "DOCS_CONSENT_URL": "https://example.com/consent",
        }
    )


def _test_config_no_docs() -> AppConfig:
    """Config with no doc URLs (triggers len(parts)==2 branch)."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///",
            "ADMIN_USERNAME": "a",
            "ADMIN_PASSWORD": "p",
            "ADMIN_SECRET": "s",
            "KAFKA_ENABLED": "false",
            "FEEDBACK_ENABLED": "false",
            "ROLE_REMINDER_ENABLED": "false",
            "REDIS_URL": "redis://",
            "USE_REDIS_STORAGE": "false",
            "DOCS_OFFER_URL": "",
            "DOCS_PRIVACY_URL": "",
            "DOCS_CONSENT_URL": "",
        }
    )


@pytest.mark.asyncio
async def test_handle_site_link_invalid_url_sends_error(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_site_link with invalid URL sends validation error via client."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="58",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.site_link.state)
    await state.update_data(
        user_id=user.user_id,
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    message = FakeMessage(text="not-a-url", user=FakeUser(58, "adv", "Adv"))
    config = _test_config()
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_site_link(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "ссылк" in s["text"].lower() or "формат" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_site_link_session_expired_sends_message(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_site_link when user_id missing sends session expired."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(AdvertiserRegistrationStates.site_link.state)
    await state.update_data(
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    message = FakeMessage(
        text="https://example.com", user=FakeUser(59, "adv", "Adv")
    )
    config = _test_config()
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_site_link(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Сессия истекла" in s["text"] for s in client.sent_text)
    assert state.cleared or state._data.get("user_id") is None


@pytest.mark.asyncio
async def test_handle_site_link_no_docs_shows_fallback(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_site_link with no doc URLs shows fallback text."""
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="56",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text="https://x.com", user=FakeUser(56, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:site_link"
    await state.update_data(
        user_id=user.user_id,
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    config = _test_config_no_docs()
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_site_link(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
    )

    assert "Подтвердите согласие с документами" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_handle_site_link_shows_agreements(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_site_link shows agreements message with doc links."""
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="53",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(
        text="https://mysite.com", user=FakeUser(53, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:site_link"
    await state.update_data(
        user_id=user.user_id,
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    config = _test_config()
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_site_link(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
    )

    assert "Оферта" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert state.state == AdvertiserRegistrationStates.agreements
    assert state._data.get("site_link") == "https://mysite.com"


@pytest.mark.asyncio
async def test_handle_agreements_confirm_session_expired(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_agreements_confirm clears state when user_id missing."""
    message = FakeMessage(
        text=_TEXTS_RU["btn_confirm_agreement"], user=FakeUser(57, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(name="X", phone="+7")  # no user_id
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_agreements_confirm(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
    )

    assert state.cleared
    assert "Сессия истекла" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_handle_agreements_confirm_wrong_button(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_agreements_confirm rejects non-confirm text."""
    message = FakeMessage(text="Wrong", user=FakeUser(54, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000054")
    )
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await handle_agreements_confirm(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
    )

    assert state.cleared
    assert message.answers
    ans = message.answers[0]
    text = ans if isinstance(ans, str) else ans[0]
    assert "Регистрация прервана" in text or "Мой профиль" in text


@pytest.mark.asyncio
async def test_handle_agreements_confirm_success(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Confirm consent; profile is saved in site_link step."""
    from tests.helpers.factories import create_test_user

    user_id = UUID("00000000-0000-0000-0000-000000000055")
    await create_test_user(
        user_repo,
        user_id=user_id,
        external_id="55",
        username="adv55",
        status=UserStatus.ACTIVE,
    )
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    await adv_service.save_advertiser_before_agreement(
        user_id=user_id,
        phone="+79001234567",
        brand="My Brand",
        site_link="https://site.com",
        city="City",
        company_activity="Activity",
        display_name="Test Name",
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_confirm_agreement"],
        user=FakeUser(55, "adv55", "Adv"),
    )
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(user_id=user_id)

    await handle_agreements_confirm(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
    )

    assert state.cleared
    assert message.answers
    ans = message.answers[0]
    assert "UGC-креаторов" in (ans if isinstance(ans, str) else ans[0])
    profile = await advertiser_repo.get_by_user_id(user_id)
    assert profile is not None
    assert profile.phone == "+79001234567"
