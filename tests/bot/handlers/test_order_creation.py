"""Tests for order creation handlers."""

from uuid import UUID, uuid4

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeBot,
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakePhotoSize,
    FakeUser,
)
from tests.helpers.services import (
    build_contact_pricing_service,
    build_order_service,
    build_payment_service,
    build_profile_service,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import CALLBACK_PROFILE_MENU_CREATE_ORDER
from ugc_bot.bot.handlers.order_creation import (
    CONTENT_USAGE_BOTH,
    COOP_BARTER,
    COOP_BOTH,
    COOP_PAYMENT,
    DEADLINES_7,
    ORDER_PHOTO_ADD,
    ORDER_PHOTO_SKIP,
    ORDER_TYPE_UGC_ONLY,
    ORDER_TYPE_UGC_PLUS_PLACEMENT,
    OrderCreationStates,
    _deadlines_offer_from_callback,
    _parse_bloggers_callback_data,
    handle_barter_description,
    handle_bloggers_needed,
    handle_bloggers_needed_callback,
    handle_content_usage,
    handle_content_usage_callback,
    handle_cooperation_format,
    handle_cooperation_format_callback,
    handle_deadlines,
    handle_deadlines_callback,
    handle_geography,
    handle_offer_text,
    handle_order_agree_callback,
    handle_order_photo,
    handle_order_photo_callback,
    handle_order_type,
    handle_order_type_callback,
    handle_price,
    handle_product_link,
    start_order_creation,
    start_order_creation_from_profile_callback,
)
from ugc_bot.bot.handlers.order_creation_states import (
    CALLBACK_ORDER_BLOGGERS_PREFIX,
    CALLBACK_ORDER_CONTENT_BOTH,
    CALLBACK_ORDER_COOP_BARTER,
    CALLBACK_ORDER_COOP_BOTH,
    CALLBACK_ORDER_COOP_PAYMENT,
    CALLBACK_ORDER_DEADLINES_PREFIX,
    CALLBACK_ORDER_PHOTO_ADD,
    CALLBACK_ORDER_PHOTO_SKIP,
    CALLBACK_ORDER_TYPE_PLACEMENT,
    CALLBACK_ORDER_TYPE_UGC,
)
from ugc_bot.bot.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryPaymentRepository,
)
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)

# Valid offer text: min 20 chars per validator
VALID_OFFER_TEXT = "Видео с распаковкой продукта и личным отзывом."


def _make_payment_service(user_repo, advertiser_repo, order_repo, pricing_repo):
    """Create a PaymentService for order-creation tests."""
    from tests.conftest import fake_transaction_manager

    return build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        InMemoryPaymentRepository(),
        pricing_repo,
        fake_transaction_manager(),
    )


# Order config for handler tests
TEST_ALLOWED_BLOGGER_COUNTS = frozenset({1, 3, 5, 10})
TEST_MAX_ORDER_PRICE = 10_000.0


def _order_creation_config() -> AppConfig:
    """Minimal config for order creation handler tests."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )


@pytest.mark.asyncio
async def test_start_order_creation_requires_role(
    user_repo, advertiser_repo, order_repo, config, bot_texts_service
) -> None:
    """Require advertiser role before creation."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )
    msg = message.answers[0]
    assert "не найден" in msg or "not found" in msg.lower()


@pytest.mark.asyncio
async def test_start_order_creation_from_profile_callback_user_not_found(
    user_repo,
    advertiser_repo,
    order_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'Create order' callback with unknown user sends nothing."""
    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
        user=FakeUser(999),
        message=FakeMessage(),
    )
    await start_order_creation_from_profile_callback(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert not messenger_client.sent_text


@pytest.mark.asyncio
async def test_start_order_creation_from_profile_callback_no_advertiser(
    user_repo,
    advertiser_repo,
    order_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'Create order' when advertiser profile missing."""
    await create_test_user(user_repo, external_id="81", username="no_adv")
    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
        user=FakeUser(81, "no_adv"),
        message=FakeMessage(user=FakeUser(81)),
    )
    await start_order_creation_from_profile_callback(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert (
        "Профиль рекламодателя не заполнен"
        in messenger_client.sent_text[0]["text"]
    )


@pytest.mark.asyncio
async def test_start_order_creation_from_profile_callback_agreement_required(
    user_repo,
    advertiser_repo,
    order_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'Create order' when agreement not confirmed sends agreement."""
    user = await create_test_user(
        user_repo,
        external_id="82",
        username="adv_agree",
    )
    await create_test_advertiser_profile(
        advertiser_repo, user.user_id, agreement_confirmed_at=None
    )
    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
        user=FakeUser(82, "adv_agree"),
        message=FakeMessage(user=FakeUser(82)),
    )
    state = FakeFSMContext()
    await start_order_creation_from_profile_callback(
        callback,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert "согласи" in messenger_client.sent_text[0]["text"].lower()
    assert state._data.get("user_id") == user.user_id
    assert state.state == _ADVERTISER_AGREEMENTS_STATE


@pytest.mark.asyncio
async def test_start_order_creation_from_profile_callback_success(
    user_repo,
    advertiser_repo,
    order_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'Create order' with agreed advertiser shows order type."""
    user = await create_test_user(
        user_repo,
        external_id="83",
        username="adv_ok",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
        user=FakeUser(83, "adv_ok"),
        message=FakeMessage(user=FakeUser(83)),
    )
    state = FakeFSMContext()
    await start_order_creation_from_profile_callback(
        callback,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert "Что вам нужно?" in messenger_client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_order_creation_flow_new_advertiser(
    user_repo,
    advertiser_repo,
    order_repo,
    pricing_repo,
    config,
    bot_texts_service,
) -> None:
    """Flow: order_type -> offer_text -> cooperation -> price -> product_link.

    Then content_usage, deadlines, geography.
    """

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await create_test_user(
        user_repo,
        external_id="5",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    message = FakeMessage(text=None, user=FakeUser(5, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )
    assert "Что вам нужно?" in message.answers[0]

    await handle_order_type(
        FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_offer_text(
        FakeMessage(text=VALID_OFFER_TEXT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_cooperation_format(
        FakeMessage(text=COOP_PAYMENT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_price(
        FakeMessage(text="1000", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_bloggers_needed(
        FakeMessage(text="3", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(5, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(5, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(5, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(5, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service(
        {3: 1500.0}, pricing_repo
    )
    await handle_geography(
        FakeMessage(
            text="Казань, Москва", user=FakeUser(5, "adv", "Adv"), bot=bot
        ),
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )
    assert bot.invoices
    assert len(order_repo.orders) == 1


@pytest.mark.asyncio
async def test_order_creation_flow_with_barter(
    user_repo,
    advertiser_repo,
    order_repo,
    pricing_repo,
    config,
    bot_texts_service,
) -> None:
    """Flow with barter: order_type -> offer_text -> cooperation -> barter."""

    from tests.helpers.factories import create_test_order

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="6",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000801"),
        product_link="https://example.com",
        offer_text="Old",
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(text=None, user=FakeUser(6, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    await handle_order_type(
        FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_offer_text(
        FakeMessage(text=VALID_OFFER_TEXT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_cooperation_format(
        FakeMessage(text=COOP_BARTER, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_barter_description(
        FakeMessage(text="Barter product with delivery", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_bloggers_needed(
        FakeMessage(text="5", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(6, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(6, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(6, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(6, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service(
        {5: 2500.0}, pricing_repo
    )
    await handle_geography(
        FakeMessage(text="РФ", user=FakeUser(6, "adv", "Adv"), bot=bot),
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )
    assert bot.invoices
    assert len(order_repo.orders) == 2


@pytest.mark.asyncio
async def test_start_order_creation_no_advertiser_profile(
    user_repo, advertiser_repo, order_repo, config, bot_texts_service
) -> None:
    """Reject when user has no advertiser profile."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    await user_service.set_user(
        external_id="8",
        messenger_type=MessengerType.TELEGRAM,
        username="no_adv",
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    message = FakeMessage(text=None, user=FakeUser(8, "no_adv", "User"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Профиль рекламодателя" in text or "register_advertiser" in text


@pytest.mark.asyncio
async def test_start_order_creation_shows_agreement_when_not_confirmed(
    user_repo, advertiser_repo, order_repo, config, bot_texts_service
) -> None:
    """Advertiser with profile but agreement not confirmed sees agreement."""

    from tests.helpers.factories import (
        create_test_advertiser_profile,
        create_test_user,
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await create_test_user(
        user_repo,
        external_id="9",
        username="adv_no_agreement",
    )
    await create_test_advertiser_profile(
        advertiser_repo, user.user_id, agreement_confirmed_at=None
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    message = FakeMessage(text=None, user=FakeUser(9, "adv_no_agreement"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "согласи" in text.lower()
    assert "Что вам нужно?" not in text


@pytest.mark.asyncio
async def test_start_order_creation_blocked_user(
    user_repo, advertiser_repo, order_repo, config, bot_texts_service
) -> None:
    """Block order creation for blocked users."""

    from tests.helpers.factories import create_test_user

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000701"),
        external_id="7",
        username="blocked",
        status=UserStatus.BLOCKED,
    )
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage(text=None, user=FakeUser(7, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_bloggers_needed_only_3_5_10(config, bot_texts_service) -> None:
    """Reject invalid bloggers count (only 3, 5, 10 allowed)."""

    state = FakeFSMContext()
    message = FakeMessage(text="20", user=None)
    await handle_bloggers_needed(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "1, 3, 5, 10" in text or "3, 5, 10" in text


@pytest.mark.asyncio
async def test_handle_price_exceeds_max_rejected(
    config, bot_texts_service
) -> None:
    """Reject price exceeding max order price limit."""

    state = FakeFSMContext()
    overflow_price = str(int(TEST_MAX_ORDER_PRICE) + 1)
    message = FakeMessage(text=overflow_price, user=None)
    await handle_price(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "превышает" in text


@pytest.mark.asyncio
async def test_handle_order_type_invalid(config, bot_texts_service) -> None:
    """Reject invalid order type choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_order_type(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_offer_text_empty(config, bot_texts_service) -> None:
    """Reject empty or too short offer text."""

    state = FakeFSMContext()
    message = FakeMessage(text="   ", user=None)
    await handle_offer_text(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "20" in text or "символ" in text.lower()


@pytest.mark.asyncio
async def test_handle_cooperation_format_invalid(
    config, bot_texts_service
) -> None:
    """Reject invalid cooperation format."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_cooperation_format(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_cooperation_format_invalid_with_client(
    config, bot_texts_service
) -> None:
    """Invalid cooperation format sends prompt via client."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.cooperation_format.state)
    message = FakeMessage(text="Другое", user=FakeUser(1, "u", "U"))

    await handle_cooperation_format(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Выберите один из вариантов" in s["text"] for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_price_negative(config, bot_texts_service) -> None:
    """Reject negative price."""

    state = FakeFSMContext()
    message = FakeMessage(text="-100", user=None)
    await handle_price(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "больше 0" in text or "отрицательной" in text


@pytest.mark.asyncio
async def test_handle_price_with_coop_both_asks_barter_description(
    config, bot_texts_service
) -> None:
    """When cooperation_format is COOP_BOTH, price step asks barter next."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.price.state)
    await state.update_data(cooperation_format=COOP_BOTH)
    message = FakeMessage(text="1000", user=FakeUser(1, "u", "U"))

    await handle_price(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.barter_description.state
    assert any("бартер" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_order_creation_flow_coop_both(
    user_repo,
    advertiser_repo,
    order_repo,
    pricing_repo,
    config,
    bot_texts_service,
) -> None:
    """Flow with COOP_BOTH: price -> barter (required) -> bloggers -> ..."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="13",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    message = FakeMessage(text=None, user=FakeUser(13, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    await handle_order_type(
        FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_offer_text(
        FakeMessage(text=VALID_OFFER_TEXT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_cooperation_format(
        FakeMessage(text=COOP_BOTH, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_price(
        FakeMessage(text="1500", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_barter_description(
        FakeMessage(text="Product + delivery", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_bloggers_needed(
        FakeMessage(text="5", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_product_link(
        FakeMessage(
            text="https://example.com", user=FakeUser(13, "adv", "Adv")
        ),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(13, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(13, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(13, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service(
        {5: 2500.0}, pricing_repo
    )
    await handle_geography(
        FakeMessage(text="Москва", user=FakeUser(13, "adv", "Adv"), bot=bot),
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert bot.invoices
    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    assert order.price == 1500.0
    assert order.barter_description == "Product + delivery"


@pytest.mark.asyncio
async def test_handle_barter_description_empty_when_coop_both(
    config, bot_texts_service
) -> None:
    """Reject empty barter when cooperation format is COOP_BOTH."""

    state = FakeFSMContext()
    state._data = {"cooperation_format": COOP_BOTH}
    message = FakeMessage(text="   ", user=None)
    await handle_barter_description(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "бартер" in text.lower()


@pytest.mark.asyncio
async def test_handle_product_link_empty(config, bot_texts_service) -> None:
    """Reject empty product link."""

    state = FakeFSMContext()
    message = FakeMessage(text="", user=None)
    await handle_product_link(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "пустой" in text.lower()


@pytest.mark.asyncio
async def test_handle_order_photo_skip(config, bot_texts_service) -> None:
    """When user clicks Пропустить, proceed to content_usage."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(1, "u", "U"))
    await handle_order_photo(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Где вы планируете использовать" in text
    assert state.state == OrderCreationStates.content_usage


@pytest.mark.asyncio
async def test_handle_order_photo_add_then_photo(
    config, bot_texts_service
) -> None:
    """User sends photo after Add: save file_id, proceed to content_usage."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(
        photo=[FakePhotoSize("AgACAgIAAxkB")],
        user=FakeUser(1, "u", "U"),
    )
    await handle_order_photo(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Где вы планируете использовать" in text
    assert state.state == OrderCreationStates.content_usage
    data = await state.get_data()
    assert data.get("product_photo_file_id") == "AgACAgIAAxkB"


@pytest.mark.asyncio
async def test_handle_order_photo_add_prompts_upload(
    config, bot_texts_service
) -> None:
    """When user clicks Добавить фото, prompt to send photo."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(text=ORDER_PHOTO_ADD, user=FakeUser(1, "u", "U"))
    await handle_order_photo(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Отправьте фото" in text
    assert state.state == OrderCreationStates.order_photo


@pytest.mark.asyncio
async def test_handle_content_usage_invalid(config, bot_texts_service) -> None:
    """Reject invalid content usage choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_content_usage(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_deadlines_invalid(config, bot_texts_service) -> None:
    """Reject invalid deadlines choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_deadlines(
        message, state, config=config, bot_texts_service=bot_texts_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_geography_empty(
    user_repo, advertiser_repo, order_repo, pricing_repo, bot_texts_service
) -> None:
    """Reject empty geography."""

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service(
        {3: 1500.0}, pricing_repo
    )

    state = FakeFSMContext()
    state._data = {
        "user_id": UUID("00000000-0000-0000-0000-000000000001"),
        "order_type": "ugc_only",
        "offer_text": "Offer",
        "cooperation_format": COOP_PAYMENT,
        "price": 1000.0,
        "bloggers_needed": 3,
        "product_link": "https://example.com",
        "content_usage": "соцсети",
        "deadlines": "7 дней",
    }
    message = FakeMessage(text="   ", user=FakeUser(1))

    await handle_geography(
        message,
        state,
        order_service,
        profile_service,
        user_role_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "один вариант" in text.lower() and "город" in text.lower()


@pytest.mark.asyncio
async def test_handle_geography_invalid_order_type(
    user_repo, advertiser_repo, order_repo, pricing_repo, bot_texts_service
) -> None:
    """Handle invalid order_type in state (fallback to UGC_ONLY)."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    state = FakeFSMContext()
    state._data = {
        "user_id": user.user_id,
        "order_type": "invalid_type",
        "offer_text": "Offer",
        "cooperation_format": COOP_PAYMENT,
        "price": 1000.0,
        "bloggers_needed": 3,
        "product_link": "https://example.com",
        "content_usage": "соцсети",
        "deadlines": "7 дней",
    }

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service(
        {3: 1500.0}, pricing_repo
    )

    message = FakeMessage(
        text="Москва", user=FakeUser(15, "adv", "Adv"), bot=bot
    )

    await handle_geography(
        message,
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    from ugc_bot.domain.enums import OrderType

    assert order.order_type == OrderType.UGC_ONLY


@pytest.mark.asyncio
async def test_order_creation_flow_ugc_plus_placement(
    user_repo,
    advertiser_repo,
    order_repo,
    pricing_repo,
    config,
    bot_texts_service,
) -> None:
    """Flow with ORDER_TYPE_UGC_PLUS_PLACEMENT."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="16",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    message = FakeMessage(text=None, user=FakeUser(16, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        config,
        bot_texts_service=bot_texts_service,
    )
    await handle_order_type(
        FakeMessage(text=ORDER_TYPE_UGC_PLUS_PLACEMENT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_offer_text(
        FakeMessage(text=VALID_OFFER_TEXT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_cooperation_format(
        FakeMessage(text=COOP_PAYMENT, user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_price(
        FakeMessage(text="1000", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_bloggers_needed(
        FakeMessage(text="3", user=None),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
    )
    await handle_product_link(
        FakeMessage(
            text="https://example.com", user=FakeUser(16, "adv", "Adv")
        ),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(16, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(16, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(16, "adv", "Adv")),
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service(
        {3: 1500.0}, pricing_repo
    )
    await handle_geography(
        FakeMessage(text="Казань", user=FakeUser(16, "adv", "Adv"), bot=bot),
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    from ugc_bot.domain.enums import OrderType

    assert order.order_type == OrderType.UGC_PLUS_PLACEMENT


@pytest.mark.asyncio
async def test_handle_geography_session_expired(
    user_repo, advertiser_repo, order_repo, pricing_repo, bot_texts_service
) -> None:
    """Show session expired when user_id is missing from state."""

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service(
        {3: 1500.0}, pricing_repo
    )

    state = FakeFSMContext()
    state._data = {
        "order_type": "ugc_only",
        "offer_text": "Offer",
        "cooperation_format": COOP_PAYMENT,
        "price": 1000.0,
        "bloggers_needed": 3,
        "product_link": "https://example.com",
        "content_usage": "соцсети",
        "deadlines": "7 дней",
    }
    message = FakeMessage(text="Москва", user=FakeUser(1))

    await handle_geography(
        message,
        state,
        order_service,
        profile_service,
        user_role_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert message.answers
    assert "Сессия истекла" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_geography_contact_price_not_configured(
    user_repo, advertiser_repo, order_repo, pricing_repo, bot_texts_service
) -> None:
    """Show error when contact pricing is not configured for bloggers count."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    state = FakeFSMContext()
    state._data = {
        "user_id": user.user_id,
        "order_type": "ugc_only",
        "offer_text": "Offer",
        "cooperation_format": COOP_PAYMENT,
        "price": 1000.0,
        "bloggers_needed": 3,
        "product_link": "https://example.com",
        "content_usage": "соцсети",
        "deadlines": "7 дней",
    }

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service({}, pricing_repo)

    message = FakeMessage(text="Москва", user=FakeUser(14, "adv", "Adv"))

    await handle_geography(
        message,
        state,
        order_service,
        profile_service,
        user_service,
        config,
        bot_texts_service,
        pricing_service,
        content_moderation_service=ContentModerationService(),
        payment_service=_make_payment_service(
            user_repo, advertiser_repo, order_repo, pricing_repo
        ),
    )

    assert len(order_repo.orders) == 1
    assert len(message.answers) >= 1
    texts = [
        ans[0] if isinstance(ans, tuple) else ans for ans in message.answers
    ]
    assert any("Стоимость доступа" in t or "настроена" in t for t in texts)


def _make_callback(
    data: str,
    user_id: int = 5,
    username: str = "adv",
) -> FakeCallback:
    """Build FakeCallback with message.chat.id set for adapter."""
    user = FakeUser(user_id, username, "User")
    return FakeCallback(
        data=data,
        user=user,
        message=FakeMessage(user=user),
    )


@pytest.mark.asyncio
async def test_order_type_callback_sets_state_and_asks_offer_text(
    config, bot_texts_service
) -> None:
    """handle_order_type_callback stores type and sends offer text step."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_type.state)
    callback = _make_callback(CALLBACK_ORDER_TYPE_UGC)

    await handle_order_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.offer_text.state
    assert state._data.get("order_type") == "ugc_only"
    assert len(client.sent_text) >= 1
    assert "Кратко опишите задачу" in client.sent_text[0]["text"]
    assert len(client.answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_cooperation_format_callback_payment_sets_price_state(
    config, bot_texts_service
) -> None:
    """handle_cooperation_format_callback with payment asks for price."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.cooperation_format.state)
    callback = _make_callback(CALLBACK_ORDER_COOP_PAYMENT)

    await handle_cooperation_format_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.price.state
    assert state._data.get("cooperation_format") == COOP_PAYMENT
    assert any("Бюджет за 1 UGC" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_cooperation_format_callback_barter_asks_barter_description(
    config, bot_texts_service
) -> None:
    """Cooperation callback with barter asks barter description."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.cooperation_format.state)
    callback = _make_callback(CALLBACK_ORDER_COOP_BARTER)

    await handle_cooperation_format_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.barter_description.state
    assert any("бартер" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_cooperation_format_callback_both_asks_price(
    config, bot_texts_service
) -> None:
    """handle_cooperation_format_callback with both asks price."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.cooperation_format.state)
    callback = _make_callback(CALLBACK_ORDER_COOP_BOTH)

    await handle_cooperation_format_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.price.state
    assert any("Бюджет за 1 UGC" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_order_type_callback_placement_sets_state(
    config, bot_texts_service
) -> None:
    """handle_order_type_callback with placement stores type and asks offer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_type.state)
    callback = _make_callback(CALLBACK_ORDER_TYPE_PLACEMENT)

    await handle_order_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state._data.get("order_type") == "ugc_plus_placement"
    assert "Кратко опишите задачу" in client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_handle_price_invalid_number_sends_message(
    config, bot_texts_service
) -> None:
    """handle_price with non-numeric text sends error."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.price.state)
    message = FakeMessage(text="abc", user=FakeUser(1, "u", "U"))

    await handle_price(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        max_order_price=TEST_MAX_ORDER_PRICE,
        currency_symbol="₽",
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("число" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_bloggers_needed_callback_invalid_data_only_answers(
    config, bot_texts_service
) -> None:
    """When callback data has invalid count (e.g. non-int), only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.bloggers_needed.state)
    callback = _make_callback(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}abc")

    await handle_bloggers_needed_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_order_photo_callback_add_prompts_upload(
    config, bot_texts_service
) -> None:
    """handle_order_photo_callback with add asks for photo."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_photo.state)
    callback = _make_callback(CALLBACK_ORDER_PHOTO_ADD)

    await handle_order_photo_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Отправьте фото" in s["text"] for s in client.sent_text)
    assert state.state == OrderCreationStates.order_photo.state


@pytest.mark.asyncio
async def test_handle_order_photo_message_add_sends_upload_prompt(
    config, bot_texts_service
) -> None:
    """Order photo message Add sends upload prompt via client/adapter."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_photo.state)
    message = FakeMessage(text=ORDER_PHOTO_ADD, user=FakeUser(1, "u", "U"))

    await handle_order_photo(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Отправьте фото" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_order_photo_invalid_sends_prompt(
    config, bot_texts_service
) -> None:
    """handle_order_photo with invalid text sends choose prompt."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_photo.state)
    message = FakeMessage(text="другое", user=FakeUser(1, "u", "U"))

    await handle_order_photo(
        message,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Добавить фото" in s["text"] or "Пропустить" in s["text"]
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_content_usage_callback_unknown_data_only_answers(
    config, bot_texts_service
) -> None:
    """When content_usage callback data is unknown, only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.content_usage.state)
    callback = _make_callback("order:content:unknown")

    await handle_content_usage_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_deadlines_callback_invalid_data_only_answers(
    config, bot_texts_service
) -> None:
    """When deadlines callback data is invalid, only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.deadlines.state)
    callback = _make_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}99")

    await handle_deadlines_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


def test_parse_bloggers_callback_data_empty_returns_none() -> None:
    """_parse_bloggers_callback_data returns None for empty or wrong prefix."""
    assert _parse_bloggers_callback_data("") is None
    assert _parse_bloggers_callback_data("other:prefix:3") is None


def test_parse_bloggers_callback_data_invalid_suffix_returns_none() -> None:
    """_parse_bloggers_callback_data returns None when suffix is not int."""
    data = f"{CALLBACK_ORDER_BLOGGERS_PREFIX}abc"
    assert _parse_bloggers_callback_data(data) is None


def test_parse_bloggers_callback_data_valid_returns_int() -> None:
    """_parse_bloggers_callback_data returns int for valid suffix."""
    data = f"{CALLBACK_ORDER_BLOGGERS_PREFIX}3"
    assert _parse_bloggers_callback_data(data) == 3


def test_deadlines_offer_from_callback_bad_prefix_returns_none() -> None:
    """_deadlines_offer_from_callback returns None for bad prefix."""
    assert _deadlines_offer_from_callback("") is None
    assert _deadlines_offer_from_callback("other:prefix:7") is None


@pytest.mark.asyncio
async def test_order_agree_callback_confirms_and_shows_order_type(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """handle_order_agree_callback confirms agreement and shows order type."""
    from tests.helpers.factories import (
        create_test_advertiser_profile,
        create_test_user,
    )

    user = await create_test_user(
        user_repo,
        external_id="99",
        username="adv_agree",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
    await state.update_data(
        flow_type="order_creation",
        user_id=user.user_id,
    )
    callback = _make_callback("order:agree", user_id=99, username="adv_agree")

    await handle_order_agree_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.order_type.state
    texts = [s["text"] for s in client.sent_text]
    assert any("Что вам нужно?" in t or "What do you need?" in t for t in texts)
    assert len(client.answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_bloggers_needed_callback_sets_state(
    config, bot_texts_service
) -> None:
    """handle_bloggers_needed_callback stores count and asks product link."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.bloggers_needed.state)
    callback = _make_callback(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}3")

    await handle_bloggers_needed_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.product_link.state
    assert state._data.get("bloggers_needed") == 3
    assert any(
        "ссылку на продукт" in s["text"].lower() for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_order_photo_callback_skip_sets_state(
    config, bot_texts_service
) -> None:
    """handle_order_photo_callback with skip goes to content_usage."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_photo.state)
    callback = _make_callback(CALLBACK_ORDER_PHOTO_SKIP)

    await handle_order_photo_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.content_usage.state
    assert any(
        "Где вы планируете использовать" in s["text"] for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_content_usage_callback_sets_state(
    config, bot_texts_service
) -> None:
    """handle_content_usage_callback stores choice and asks deadlines."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.content_usage.state)
    callback = _make_callback(CALLBACK_ORDER_CONTENT_BOTH)

    await handle_content_usage_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.deadlines.state
    assert state._data.get("content_usage") is not None


@pytest.mark.asyncio
async def test_deadlines_callback_sets_state(config, bot_texts_service) -> None:
    """handle_deadlines_callback stores choice and asks geography."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.deadlines.state)
    callback = _make_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}7")

    await handle_deadlines_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert state.state == OrderCreationStates.geography.state
    assert state._data.get("deadlines") is not None


@pytest.mark.asyncio
async def test_order_agree_callback_wrong_state_only_answers(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When state is not agreements, callback only answers, no flow."""
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_type.state)
    callback = _make_callback("order:agree")

    await handle_order_agree_callback(
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
async def test_order_agree_callback_no_user_id_sends_session_expired(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When user_id missing in state, send session expired and clear."""
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
    await state.update_data(flow_type="order_creation")
    callback = _make_callback("order:agree")

    await handle_order_agree_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    texts = [s["text"] for s in client.sent_text]
    assert any("Сессия истекла" in t or "Session expired" in t for t in texts)
    assert state.cleared or state._data.get("flow_type") is None


@pytest.mark.asyncio
async def test_order_agree_callback_wrong_flow_type_only_answers(
    user_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When flow_type is not order_creation, callback only answers."""
    user = await create_test_user(
        user_repo, external_id="98", username="adv_flow"
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
    await state.update_data(flow_type="other", user_id=user.user_id)
    callback = _make_callback("order:agree", user_id=98, username="adv_flow")

    await handle_order_agree_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        advertiser_registration_service=adv_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) == 0
    assert len(client.answered_callbacks) == 1


@pytest.mark.asyncio
async def test_order_type_callback_unknown_data_only_answers(
    config, bot_texts_service
) -> None:
    """When callback data is not UGC/placement, only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.order_type.state)
    callback = _make_callback("order:type:unknown")

    await handle_order_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0
    assert state._data.get("order_type") is None


@pytest.mark.asyncio
async def test_order_type_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not order_type, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.offer_text.state)
    callback = _make_callback(CALLBACK_ORDER_TYPE_UGC)

    await handle_order_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0
    assert state._data.get("order_type") is None


@pytest.mark.asyncio
async def test_cooperation_format_callback_unknown_data_only_answers(
    config, bot_texts_service
) -> None:
    """When callback data is not barter/payment/both, only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.cooperation_format.state)
    callback = _make_callback("order:coop:unknown")

    await handle_cooperation_format_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_cooperation_format_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not cooperation_format, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.price.state)
    callback = _make_callback(CALLBACK_ORDER_COOP_PAYMENT)

    await handle_cooperation_format_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_bloggers_needed_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not bloggers_needed, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.product_link.state)
    callback = _make_callback(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}3")

    await handle_bloggers_needed_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_bloggers_needed_callback_invalid_count_only_answers(
    config, bot_texts_service
) -> None:
    """When callback data has count not in allowed set, only answer."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.bloggers_needed.state)
    callback = _make_callback(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}99")

    await handle_bloggers_needed_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=TEST_ALLOWED_BLOGGER_COUNTS,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0
    assert state._data.get("bloggers_needed") is None


@pytest.mark.asyncio
async def test_order_photo_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not order_photo, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.content_usage.state)
    callback = _make_callback(CALLBACK_ORDER_PHOTO_SKIP)

    await handle_order_photo_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert state.state == OrderCreationStates.content_usage.state


@pytest.mark.asyncio
async def test_content_usage_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not content_usage, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.deadlines.state)
    callback = _make_callback(CALLBACK_ORDER_CONTENT_BOTH)

    await handle_content_usage_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_deadlines_callback_wrong_state_only_answers(
    config, bot_texts_service
) -> None:
    """When state is not deadlines, callback only answers."""
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(OrderCreationStates.geography.state)
    callback = _make_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}7")

    await handle_deadlines_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_order_type_callback_shows_selection(bot_texts_service) -> None:
    """After order type chosen, message is edited to show the selected label."""
    state = FakeFSMContext(state=OrderCreationStates.order_type.state)
    await state.update_data(user_id=str(uuid4()))
    msg = FakeMessage(text="Что вам нужно?", user=FakeUser(42, "user", "User"))
    callback = FakeCallback(
        data=CALLBACK_ORDER_TYPE_UGC,
        user=FakeUser(42, "user", "User"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_order_type_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Что вам нужно?" in e["text"] and ORDER_TYPE_UGC_ONLY in e["text"]
        for e in client.edited_text
    )


@pytest.mark.asyncio
async def test_cooperation_format_callback_shows_selection(
    bot_texts_service,
) -> None:
    """After coop format chosen, message edited to show selected label."""
    state = FakeFSMContext(state=OrderCreationStates.cooperation_format.state)
    await state.update_data(user_id=str(uuid4()))
    msg = FakeMessage(
        text="Формат сотрудничества?", user=FakeUser(42, "u", "U")
    )
    callback = FakeCallback(
        data=CALLBACK_ORDER_COOP_PAYMENT,
        user=FakeUser(42, "u", "U"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_cooperation_format_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Формат сотрудничества?" in e["text"] and COOP_PAYMENT in e["text"]
        for e in client.edited_text
    )


@pytest.mark.asyncio
async def test_bloggers_needed_callback_shows_selection(
    bot_texts_service,
) -> None:
    """After bloggers count chosen, message edited to show count."""
    state = FakeFSMContext(state=OrderCreationStates.bloggers_needed.state)
    await state.update_data(user_id=str(uuid4()))
    counts = frozenset({1, 3, 5})
    msg = FakeMessage(text="Сколько креаторов?", user=FakeUser(42, "u", "U"))
    callback = FakeCallback(
        data=f"{CALLBACK_ORDER_BLOGGERS_PREFIX}3",
        user=FakeUser(42, "u", "U"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_bloggers_needed_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        allowed_blogger_counts=counts,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Сколько креаторов?" in e["text"] and "3" in e["text"]
        for e in client.edited_text
    )


@pytest.mark.asyncio
async def test_deadlines_callback_shows_selection(bot_texts_service) -> None:
    """After deadline chosen, message edited to show deadline label."""
    state = FakeFSMContext(state=OrderCreationStates.deadlines.state)
    await state.update_data(user_id=str(uuid4()))
    msg = FakeMessage(text="Дедлайн?", user=FakeUser(42, "u", "U"))
    callback = FakeCallback(
        data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}7",
        user=FakeUser(42, "u", "U"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_deadlines_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Дедлайн?" in e["text"] and DEADLINES_7 in e["text"]
        for e in client.edited_text
    )


@pytest.mark.asyncio
async def test_order_photo_skip_callback_shows_selection(
    bot_texts_service,
) -> None:
    """After photo skip chosen, message edited to show skip label."""
    state = FakeFSMContext(state=OrderCreationStates.order_photo.state)
    msg = FakeMessage(text="Добавить фото?", user=FakeUser(42, "u", "U"))
    callback = FakeCallback(
        data=CALLBACK_ORDER_PHOTO_SKIP,
        user=FakeUser(42, "u", "U"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_order_photo_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Добавить фото?" in e["text"] and ORDER_PHOTO_SKIP in e["text"]
        for e in client.edited_text
    )


@pytest.mark.asyncio
async def test_content_usage_callback_shows_selection(
    bot_texts_service,
) -> None:
    """After content usage chosen, message edited to show display label."""
    state = FakeFSMContext(state=OrderCreationStates.content_usage.state)
    msg = FakeMessage(text="Где используете?", user=FakeUser(42, "u", "U"))
    callback = FakeCallback(
        data=CALLBACK_ORDER_CONTENT_BOTH,
        user=FakeUser(42, "u", "U"),
        message=msg,
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()

    await handle_content_usage_callback(
        callback,
        state=state,
        config=_order_creation_config(),
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any(
        "Где используете?" in e["text"] and CONTENT_USAGE_BOTH in e["text"]
        for e in client.edited_text
    )
