"""Tests for order creation handlers."""

from uuid import UUID

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.order_creation import (
    handle_barter_choice,
    handle_barter_description,
    handle_bloggers_needed,
    handle_offer_text,
    handle_price,
    handle_product_link,
    handle_ugc_requirements,
    start_order_creation,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from tests.helpers.fakes import FakeBot, FakeFSMContext, FakeMessage, FakeUser
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
        message, state, user_service, profile_service, order_service
    )
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_order_creation_flow_new_advertiser(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """New advertisers skip barter step."""

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
        message, state, user_service, profile_service, order_service
    )
    assert state._data["is_new"] is True

    await handle_product_link(FakeMessage(text="https://example.com", user=None), state)
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_ugc_requirements(FakeMessage(text="пропустить", user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({3: 1500.0}, pricing_repo)
    await handle_bloggers_needed(
        FakeMessage(text="3", user=FakeUser(5, "adv", "Adv"), bot=bot),
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
    """Handle barter flow for existing advertisers."""

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
        message, state, user_service, profile_service, order_service
    )

    await handle_product_link(FakeMessage(text="https://example.com", user=None), state)
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_ugc_requirements(FakeMessage(text="пропустить", user=None), state)
    await handle_barter_choice(FakeMessage(text="Да", user=None), state)
    await handle_barter_description(FakeMessage(text="Barter", user=None), state)
    await handle_price(FakeMessage(text="1500", user=None), state)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = await build_contact_pricing_service({20: 5000.0}, pricing_repo)
    await handle_bloggers_needed(
        FakeMessage(text="20", user=FakeUser(6, "adv", "Adv"), bot=bot),
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
        message, state, user_service, profile_service, order_service
    )

    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_bloggers_needed_limit_for_new_advertiser(
    user_repo, advertiser_repo, order_repo, pricing_repo
) -> None:
    """Reject invalid bloggers count for NEW advertisers."""

    order_service = build_order_service(user_repo, advertiser_repo, order_repo)
    state = FakeFSMContext()
    await state.update_data(is_new=True)

    message = FakeMessage(text="20", user=None)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = await build_contact_pricing_service({20: 5000.0}, pricing_repo)
    await handle_bloggers_needed(message, state, order_service, config, pricing_service)

    assert "NEW рекламодатели" in message.answers[0]
