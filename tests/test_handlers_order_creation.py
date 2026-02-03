"""Tests for order creation handlers."""

from uuid import UUID

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.order_creation import (
    COOP_BARTER,
    COOP_PAYMENT,
    CONTENT_USAGE_BOTH,
    DEADLINES_7,
    ORDER_TYPE_UGC_ONLY,
    handle_barter_description,
    handle_bloggers_needed,
    handle_content_usage,
    handle_cooperation_format,
    handle_deadlines,
    handle_geography,
    handle_offer_text,
    handle_order_type,
    handle_price,
    handle_product_link,
    start_order_creation,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from tests.helpers.fakes import (
    FakeBot,
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
)
from tests.helpers.factories import create_test_advertiser_profile
from tests.helpers.services import (
    build_contact_pricing_service,
    build_order_service,
    build_profile_service,
)


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
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_PAYMENT, user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    await handle_bloggers_needed(FakeMessage(text="3", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(5, "adv", "Adv")), state
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
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_cooperation_format(FakeMessage(text=COOP_BARTER, user=None), state)
    await handle_barter_description(FakeMessage(text="Barter", user=None), state)
    await handle_bloggers_needed(FakeMessage(text="5", user=None), state)
    await handle_product_link(
        FakeMessage(text="https://example.com", user=FakeUser(6, "adv", "Adv")), state
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
