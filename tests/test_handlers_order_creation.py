"""Tests for order creation handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.services.order_service import MAX_ORDER_PRICE
from ugc_bot.bot.handlers.keyboards import (
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
)
from ugc_bot.bot.handlers.order_creation import (
    COOP_BARTER,
    COOP_BOTH,
    COOP_PAYMENT,
    CONTENT_USAGE_BOTH,
    DEADLINES_7,
    ORDER_PHOTO_ADD,
    ORDER_PHOTO_SKIP,
    ORDER_TYPE_UGC_ONLY,
    ORDER_TYPE_UGC_PLUS_PLACEMENT,
    OrderCreationStates,
    handle_barter_description,
    handle_bloggers_needed,
    handle_content_usage,
    handle_cooperation_format,
    handle_deadlines,
    handle_geography,
    handle_offer_text,
    handle_order_photo,
    handle_order_type,
    handle_price,
    handle_product_link,
    order_draft_choice,
    start_order_creation,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import FsmDraft
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from tests.helpers.fakes import (
    FakeBot,
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakePhotoSize,
    FakeUser,
    RecordingFsmDraftService,
)
from tests.helpers.factories import create_test_advertiser_profile
from tests.helpers.services import (
    build_contact_pricing_service,
    build_order_service,
    build_profile_service,
)

# Valid offer text: min 20 chars per validator
VALID_OFFER_TEXT = "Видео с распаковкой продукта и личным отзывом."


@pytest.mark.asyncio
async def test_start_order_creation_requires_role(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Require advertiser role before creation."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        FakeFsmDraftService(),
    )
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_order_creation_flow_new_advertiser(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Full flow: order_type -> offer_text -> cooperation (Оплата) -> price -> bloggers -> product_link -> content_usage -> deadlines -> geography."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    message = FakeMessage(text=None, user=FakeUser(5, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        FakeFsmDraftService(),
    )
    assert "Что вам нужно?" in message.answers[0]

    await handle_order_type(FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None), state)
    await handle_offer_text(FakeMessage(text=VALID_OFFER_TEXT, user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_PAYMENT, user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    await handle_bloggers_needed(FakeMessage(text="3", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(5, "adv", "Adv")), state
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(5, "adv", "Adv")), state
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(5, "adv", "Adv")), state
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(5, "adv", "Adv")), state
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)
    await handle_geography(
        FakeMessage(text="Казань, Москва", user=FakeUser(5, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )
    assert bot.invoices
    assert len(order_repo.orders) == 1


@pytest.mark.asyncio
async def test_order_creation_flow_with_barter(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Flow with barter: order_type -> offer_text -> cooperation (Бартер) -> barter -> bloggers -> product_link."""

    from tests.helpers.factories import create_test_order

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="6",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
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
        FakeFsmDraftService(),
    )

    await handle_order_type(FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None), state)
    await handle_offer_text(FakeMessage(text=VALID_OFFER_TEXT, user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_BARTER, user=None), state)
    await handle_barter_description(
        FakeMessage(text="Barter product with delivery", user=None), state
    )
    await handle_bloggers_needed(FakeMessage(text="5", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(6, "adv", "Adv")), state
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(6, "adv", "Adv")), state
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(6, "adv", "Adv")), state
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(6, "adv", "Adv")), state
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({5: 2500.0}, pricing_repo)
    await handle_geography(
        FakeMessage(text="РФ", user=FakeUser(6, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )
    assert bot.invoices
    assert len(order_repo.orders) == 2


@pytest.mark.asyncio
async def test_start_order_creation_no_advertiser_profile(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Reject when user has no advertiser profile."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    await user_service.set_user(
        external_id="8",
        messenger_type=MessengerType.TELEGRAM,
        username="no_adv",
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    message = FakeMessage(text=None, user=FakeUser(8, "no_adv", "User"))
    state = FakeFSMContext()

    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        FakeFsmDraftService(),
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Профиль рекламодателя" in text or "register_advertiser" in text


@pytest.mark.asyncio
async def test_start_order_creation_blocked_user(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Block order creation for blocked users."""

    from tests.helpers.factories import create_test_user

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
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
        FakeFsmDraftService(),
    )

    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_bloggers_needed_only_3_5_10() -> None:
    """Reject invalid bloggers count (only 3, 5, 10 allowed)."""

    state = FakeFSMContext()
    message = FakeMessage(text="20", user=None)
    await handle_bloggers_needed(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "3, 5 или 10" in text


@pytest.mark.asyncio
async def test_handle_price_exceeds_max_rejected() -> None:
    """Reject price exceeding NUMERIC(10,2) limit."""

    state = FakeFSMContext()
    overflow_price = str(int(MAX_ORDER_PRICE) + 1)
    message = FakeMessage(text=overflow_price, user=None)
    await handle_price(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "превышает максимально допустимую" in text


@pytest.mark.asyncio
async def test_start_order_creation_with_draft(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Show draft choice when draft exists."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    user = await user_service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    draft = FsmDraft(
        user_id=user.user_id,
        flow_type="order_creation",
        state_key="OrderCreationStates:cooperation_format",
        data={"user_id": user.user_id, "order_type": "ugc_only", "offer_text": "Draft"},
        updated_at=datetime.now(timezone.utc),
    )
    draft_service = RecordingFsmDraftService(draft_to_return=draft)

    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()

    await start_order_creation(
        message, state, user_service, profile_service, order_service, draft_service
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Черновик" in text or "черновик" in text.lower()


@pytest.mark.asyncio
async def test_order_draft_choice_resume(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Resume draft restores state and shows keyboard for that state."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    draft = FsmDraft(
        user_id=user.user_id,
        flow_type="order_creation",
        state_key="OrderCreationStates:content_usage",
        data={
            "user_id": user.user_id,
            "order_type": "ugc_only",
            "offer_text": "Offer",
            "cooperation_format": COOP_PAYMENT,
            "price": 1000.0,
            "bloggers_needed": 3,
            "product_link": "https://example.com",
        },
        updated_at=datetime.now(timezone.utc),
    )
    draft_service = RecordingFsmDraftService(draft_to_return=draft)

    message = FakeMessage(
        text=RESUME_DRAFT_BUTTON_TEXT, user=FakeUser(11, "adv", "Adv")
    )
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = OrderCreationStates.choosing_draft_restore

    await order_draft_choice(message, state, draft_service)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "UGC-видео" in text or "восстановлен" in text.lower()


@pytest.mark.asyncio
async def test_order_draft_choice_start_over(
    user_repo, advertiser_repo, order_repo
) -> None:
    """Start over clears draft and shows order type."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    draft_service = RecordingFsmDraftService(draft_to_return=None)
    message = FakeMessage(text=START_OVER_BUTTON_TEXT, user=FakeUser(12, "adv", "Adv"))
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = OrderCreationStates.choosing_draft_restore

    await order_draft_choice(message, state, draft_service)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Что вам нужно?" in text


@pytest.mark.asyncio
async def test_handle_order_type_invalid() -> None:
    """Reject invalid order type choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_order_type(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_offer_text_empty() -> None:
    """Reject empty or too short offer text."""

    state = FakeFSMContext()
    message = FakeMessage(text="   ", user=None)
    await handle_offer_text(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "20" in text or "символ" in text.lower()


@pytest.mark.asyncio
async def test_handle_cooperation_format_invalid() -> None:
    """Reject invalid cooperation format."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_cooperation_format(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_price_negative() -> None:
    """Reject negative price."""

    state = FakeFSMContext()
    message = FakeMessage(text="-100", user=None)
    await handle_price(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "больше 0" in text or "отрицательной" in text


@pytest.mark.asyncio
async def test_order_creation_flow_coop_both(
    user_repo, advertiser_repo, order_repo, pricing_repo
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
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    message = FakeMessage(text=None, user=FakeUser(13, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        FakeFsmDraftService(),
    )

    await handle_order_type(FakeMessage(text=ORDER_TYPE_UGC_ONLY, user=None), state)
    await handle_offer_text(FakeMessage(text=VALID_OFFER_TEXT, user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_BOTH, user=None), state)
    await handle_price(FakeMessage(text="1500", user=None), state)
    await handle_barter_description(
        FakeMessage(text="Product + delivery", user=None), state
    )
    await handle_bloggers_needed(FakeMessage(text="5", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(13, "adv", "Adv")), state
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(13, "adv", "Adv")), state
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(13, "adv", "Adv")), state
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(13, "adv", "Adv")), state
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({5: 2500.0}, pricing_repo)
    await handle_geography(
        FakeMessage(text="Москва", user=FakeUser(13, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )

    assert bot.invoices
    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    assert order.price == 1500.0
    assert order.barter_description == "Product + delivery"


@pytest.mark.asyncio
async def test_handle_barter_description_empty_when_coop_both() -> None:
    """Reject empty barter when cooperation format is COOP_BOTH."""

    state = FakeFSMContext()
    state._data = {"cooperation_format": COOP_BOTH}
    message = FakeMessage(text="   ", user=None)
    await handle_barter_description(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "бартер" in text.lower()


@pytest.mark.asyncio
async def test_handle_product_link_empty() -> None:
    """Reject empty product link."""

    state = FakeFSMContext()
    message = FakeMessage(text="", user=None)
    await handle_product_link(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "пустой" in text.lower()


@pytest.mark.asyncio
async def test_handle_order_photo_skip() -> None:
    """When user clicks Пропустить, proceed to content_usage."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(1, "u", "U"))
    await handle_order_photo(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Где вы планируете использовать" in text
    assert state.state == OrderCreationStates.content_usage


@pytest.mark.asyncio
async def test_handle_order_photo_add_then_photo() -> None:
    """When user sends photo after Add, save file_id and proceed to content_usage."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(
        photo=[FakePhotoSize("AgACAgIAAxkB")],
        user=FakeUser(1, "u", "U"),
    )
    await handle_order_photo(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Где вы планируете использовать" in text
    assert state.state == OrderCreationStates.content_usage
    data = await state.get_data()
    assert data.get("product_photo_file_id") == "AgACAgIAAxkB"


@pytest.mark.asyncio
async def test_handle_order_photo_add_prompts_upload() -> None:
    """When user clicks Добавить фото, prompt to send photo."""
    state = FakeFSMContext()
    state._data = {"product_link": "https://example.com"}
    state.state = OrderCreationStates.order_photo

    message = FakeMessage(text=ORDER_PHOTO_ADD, user=FakeUser(1, "u", "U"))
    await handle_order_photo(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Отправьте фото" in text
    assert state.state == OrderCreationStates.order_photo


@pytest.mark.asyncio
async def test_handle_content_usage_invalid() -> None:
    """Reject invalid content usage choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_content_usage(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_deadlines_invalid() -> None:
    """Reject invalid deadlines choice."""

    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=None)
    await handle_deadlines(message, state)

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Выберите один из вариантов" in text


@pytest.mark.asyncio
async def test_handle_geography_empty(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Reject empty geography."""

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)

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

    await handle_geography(message, state, order_service, config, pricing_service)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "географию" in text.lower()


@pytest.mark.asyncio
async def test_handle_geography_invalid_order_type(
    user_repo, advertiser_repo, order_repo, pricing_repo
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
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)

    message = FakeMessage(text="Москва", user=FakeUser(15, "adv", "Adv"), bot=bot)

    await handle_geography(message, state, order_service, config, pricing_service)

    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    from ugc_bot.domain.enums import OrderType

    assert order.order_type == OrderType.UGC_ONLY


@pytest.mark.asyncio
async def test_order_creation_flow_ugc_plus_placement(
    user_repo, advertiser_repo, order_repo, pricing_repo
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
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)

    message = FakeMessage(text=None, user=FakeUser(16, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message,
        state,
        user_service,
        profile_service,
        order_service,
        FakeFsmDraftService(),
    )
    await handle_order_type(
        FakeMessage(text=ORDER_TYPE_UGC_PLUS_PLACEMENT, user=None), state
    )
    await handle_offer_text(FakeMessage(text=VALID_OFFER_TEXT, user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_PAYMENT, user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    await handle_bloggers_needed(FakeMessage(text="3", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(16, "adv", "Adv")), state
    )
    await handle_order_photo(
        FakeMessage(text=ORDER_PHOTO_SKIP, user=FakeUser(16, "adv", "Adv")), state
    )
    await handle_content_usage(
        FakeMessage(text=CONTENT_USAGE_BOTH, user=FakeUser(16, "adv", "Adv")), state
    )
    await handle_deadlines(
        FakeMessage(text=DEADLINES_7, user=FakeUser(16, "adv", "Adv")), state
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)
    await handle_geography(
        FakeMessage(text="Казань", user=FakeUser(16, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )

    assert len(order_repo.orders) == 1
    order = list(order_repo.orders.values())[0]
    from ugc_bot.domain.enums import OrderType

    assert order.order_type == OrderType.UGC_PLUS_PLACEMENT


@pytest.mark.asyncio
async def test_handle_geography_session_expired(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Show session expired when user_id is missing from state."""

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)

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

    await handle_geography(message, state, order_service, config, pricing_service)

    assert message.answers
    assert "Сессия истекла" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_geography_contact_price_not_configured(
    user_repo, advertiser_repo, order_repo, pricing_repo
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

    await handle_geography(message, state, order_service, config, pricing_service)

    assert len(order_repo.orders) == 1
    assert len(message.answers) >= 2
    assert (
        "Стоимость доступа" in message.answers[1] or "настроена" in message.answers[1]
    )
