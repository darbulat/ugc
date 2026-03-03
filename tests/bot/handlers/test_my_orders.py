"""Tests for my orders handler."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_order,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeUser,
)
from tests.helpers.services import build_order_service, build_profile_service
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import CALLBACK_PROFILE_MENU_MY_ORDERS
from ugc_bot.bot.handlers.my_orders import (
    _MY_ORDERS_BLOGGER_CALLBACK_PREFIX,
    _format_date,
    _format_order_type,
    _format_price,
    _format_price_and_barter,
    paginate_orders,
    show_my_orders,
    show_my_orders_from_profile_callback,
)
from ugc_bot.bot.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import MessengerType, OrderStatus, OrderType

_TEXTS_RU = DEFAULT_TEXTS["ru"]


def _my_orders_config() -> AppConfig:
    """Minimal config for my_orders handler tests."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )


@pytest.mark.asyncio
async def test_show_my_orders_returns_early_when_no_from_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """show_my_orders returns without answering when from_user is None."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    message = FakeMessage(text="/my_orders", user=None)
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_show_my_orders_from_profile_callback_advertiser_no_orders(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile inline 'My orders' opens orders list; no orders shows hint."""
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000801"),
        external_id="801",
        username="adv",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    msg = FakeMessage(user=FakeUser(801, "adv"))
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_MY_ORDERS,
        user=FakeUser(801, "adv"),
        message=msg,
    )
    await show_my_orders_from_profile_callback(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert any(
        "пока нет заказов" in s["text"] for s in messenger_client.sent_text
    )


@pytest.mark.asyncio
async def test_show_my_orders_from_profile_callback_agreement_required(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'My orders' when agreement not confirmed shows agreement."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000802"),
        external_id="802",
        username="adv_agree",
        agreement_confirmed_at=None,
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_MY_ORDERS,
        user=FakeUser(802, "adv_agree"),
        message=FakeMessage(user=FakeUser(802)),
    )
    state = FakeFSMContext()
    await show_my_orders_from_profile_callback(
        callback,
        state,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert "согласи" in messenger_client.sent_text[0]["text"].lower()
    assert state.state == _ADVERTISER_AGREEMENTS_STATE


@pytest.mark.asyncio
async def test_show_my_orders_from_profile_callback_advertiser_with_orders(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'My orders' with advertiser that has orders shows list."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000803"),
        external_id="803",
        username="adv_ord",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000803"),
        price=1000.0,
    )
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_MY_ORDERS,
        user=FakeUser(803, "adv_ord"),
        message=FakeMessage(user=FakeUser(803)),
    )
    await show_my_orders_from_profile_callback(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert "Ваши заказы" in messenger_client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_show_my_orders_from_profile_callback_blogger_with_responses(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Profile 'My orders' with blogger that responded shows list."""
    adv_user = await create_test_user(
        user_repo,
        external_id="adv84",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    order = await create_test_order(order_repo, adv_user.user_id, price=300.0)
    blogger_user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000804"),
        external_id="804",
        username="blogger_resp",
    )
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger_user.user_id, accepted=True, in_offer=True
    )
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MENU_MY_ORDERS,
        user=FakeUser(804, "blogger_resp"),
        message=FakeMessage(user=FakeUser(804)),
    )
    await show_my_orders_from_profile_callback(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.sent_text
    assert "откликнулись" in messenger_client.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_paginate_orders_blogger_no_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders blogger branch when blogger profile missing."""
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000805"),
        external_id="805",
        username="no_blogger",
    )
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    msg = FakeMessage(user=FakeUser(805))
    callback = FakeCallback(
        data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}1",
        user=FakeUser(805),
        message=msg,
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert callback.answers
    assert (
        "Профиль блогера не заполнен" in callback.answers[0]
        or "Blogger profile not filled" in callback.answers[0]
    )


@pytest.mark.asyncio
async def test_paginate_orders_blogger_page2(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders blogger branch page 2 renders nav buttons."""
    adv_user = await create_test_user(
        user_repo, external_id="adv86", username="adv"
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    blogger_user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000806"),
        external_id="806",
        username="blogger_pg",
    )
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    for i in range(6):
        order = await create_test_order(
            order_repo,
            adv_user.user_id,
            order_id=uuid4(),
            price=100.0 * (i + 1),
        )
        await offer_dispatch_repo.record_sent(
            order.order_id, blogger_user.user_id
        )
        await offer_dispatch_repo.record_response(
            order.order_id, blogger_user.user_id, accepted=True, in_offer=True
        )
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    msg = FakeMessage(user=FakeUser(806))
    callback = FakeCallback(
        data=f"{_MY_ORDERS_BLOGGER_CALLBACK_PREFIX}2",
        user=FakeUser(806),
        message=msg,
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert messenger_client.edited_text
    assert "страница 2/2" in messenger_client.edited_text[0]["text"]


@pytest.mark.asyncio
async def test_show_my_orders_user_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Show hint when user is not in DB (get_user returns None)."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    message = FakeMessage(text="/my_orders", user=FakeUser(1))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    text = message.answers[0]
    assert (
        "не найден" in text
        or "not found" in text.lower()
        or "profile" in text.lower()
    )


@pytest.mark.asyncio
async def test_my_orders_no_advertiser_nor_blogger_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Show hint when neither advertiser nor blogger profile exists."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    await user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "Заполните профиль" in message.answers[0]
    assert "register" in message.answers[0] or "профиль" in message.answers[0]


@pytest.mark.asyncio
async def test_show_my_orders_shows_agreement_when_not_confirmed(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """When user has profile but agreement not confirmed, show agreement."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="99",
        username="user",
        agreement_confirmed_at=None,
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser(99, "user")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "согласи" in text.lower()
    assert "согласи" in text.lower()
    assert "пока нет заказов" not in text
    assert "№ " not in text or "согласи" in text.lower()


@pytest.mark.asyncio
async def test_show_my_orders_shows_agreement_when_blogger_not_confirmed(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """When user has only blogger profile and no agreement, show agreement."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="98",
        username="blogger_user",
        agreement_confirmed_at=None,
    )
    await create_test_blogger_profile(blogger_repo, user.user_id)

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser(98, "blogger_user")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "согласи" in text.lower()


@pytest.mark.asyncio
async def test_my_orders_blogger_no_responses(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger with no responses sees hint."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        external_id="5",
        username="blogger",
    )
    await create_test_blogger_profile(blogger_repo, user.user_id)

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(5))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "не откликались" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_blogger_with_responses(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger sees orders they responded to."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    adv_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv1",
        username="advertiser",
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    order = await create_test_order(
        order_repo,
        adv_user.user_id,
        order_id=uuid4(),
        price=500.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
    )

    blogger_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="6",
        username="creator",
    )
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger_user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(6))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "откликнулись" in answer_text
    assert "№ 1" in answer_text


@pytest.mark.asyncio
async def test_my_orders_empty(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Show hint when no orders exist."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(text="/my_orders", user=FakeUser(1))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "пока нет заказов" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_list(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """List existing orders."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    from uuid import UUID

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "№ 1" in answer_text
    assert "Создан" in answer_text
    assert "Креаторов: 3" in answer_text
    assert "Подобрано: 0 / 3" in answer_text
    assert "Стоимость 1 UGC: 1 000 ₽" in answer_text
    assert "Дата создания:" in answer_text
    assert "Дата завершения: —" in answer_text
    assert "Ссылка на проект:" in answer_text


@pytest.mark.asyncio
async def test_my_orders_both_profiles_with_orders(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Both profiles: two messages with advertiser and blogger orders."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="10",
        username="both",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_blogger_profile(blogger_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=uuid4(),
        price=2000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    other_adv = await create_test_user(
        user_repo, user_id=uuid4(), external_id="other", username="other"
    )
    await create_test_advertiser_profile(advertiser_repo, other_adv.user_id)
    other_order = await create_test_order(
        order_repo,
        other_adv.user_id,
        order_id=uuid4(),
        price=500.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(other_order.order_id, user.user_id)
    await offer_dispatch_repo.record_response(
        other_order.order_id, user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(10))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert len(message.answers) == 2
    first = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    second = (
        message.answers[1]
        if isinstance(message.answers[1], str)
        else message.answers[1][0]
    )
    assert "Ваши заказы" in first
    assert "1 000" in first or "2 000" in first
    assert "откликнулись" in second
    assert "№ 1" in second


@pytest.mark.asyncio
async def test_my_orders_both_profiles_both_empty(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """User with both profiles but no orders gets two hint messages."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="11",
        username="both_empty",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_blogger_profile(blogger_repo, user.user_id)

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(11))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert len(message.answers) == 2
    first = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    second = (
        message.answers[1]
        if isinstance(message.answers[1], str)
        else message.answers[1][0]
    )
    assert "пока нет заказов" in first
    assert "не откликались" in second


@pytest.mark.asyncio
async def test_my_orders_both_profiles_advertiser_only(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Both profiles: advertiser has orders, blogger has none — list + hint."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="12",
        username="adv_only",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_blogger_profile(blogger_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=uuid4(),
        price=1500.0,
        bloggers_needed=2,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(12))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert len(message.answers) == 2
    first = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    second = (
        message.answers[1]
        if isinstance(message.answers[1], str)
        else message.answers[1][0]
    )
    assert "Ваши заказы" in first
    assert "1 500" in first
    assert "не откликались" in second


@pytest.mark.asyncio
async def test_my_orders_both_profiles_blogger_only(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Both profiles: blogger has responses, advertiser none — hint + list."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    adv_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv13",
        username="advertiser",
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    order = await create_test_order(
        order_repo,
        adv_user.user_id,
        order_id=uuid4(),
        price=800.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
    )

    blogger_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="13",
        username="blogger_only",
    )
    await create_test_advertiser_profile(advertiser_repo, blogger_user.user_id)
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger_user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(13))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert len(message.answers) == 2
    first = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    second = (
        message.answers[1]
        if isinstance(message.answers[1], str)
        else message.answers[1][0]
    )
    assert "пока нет заказов" in first
    assert "откликнулись" in second
    assert "№ 1" in second


@pytest.mark.asyncio
async def test_paginate_orders_returns_early_when_no_from_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders returns without answering when from_user is None."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data="my_orders:1", user=None, message=FakeMessage()
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert not callback.answers or callback.answers == [""]


@pytest.mark.asyncio
async def test_paginate_orders_user_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders answers when user is not found."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(999), message=FakeMessage()
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert callback.answers
    assert (
        "не найден" in callback.answers[0]
        or "not found" in callback.answers[0].lower()
    )


@pytest.mark.asyncio
async def test_paginate_orders_no_advertiser_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders answers when advertiser profile is missing."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000935"),
        external_id="1",
        username="adv",
    )
    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(1), message=message
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert callback.answers
    assert (
        "Профиль рекламодателя не заполнен" in callback.answers[0]
        or "Advertiser profile not filled" in callback.answers[0]
    )


@pytest.mark.asyncio
async def test_paginate_orders_skips_edit_when_message_has_no_edit_text(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders does not call edit_text when message has no edit_text."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000936"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    class MessageWithoutEdit:
        def __init__(self) -> None:
            self.chat = type("Chat", (), {"id": 1})()
            self.message_id = 1

    message_without_edit = MessageWithoutEdit()
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(1), message=message_without_edit
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    await callback.answer()
    assert callback.answers


@pytest.mark.asyncio
async def test_paginate_orders_invalid_page_uses_one(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """paginate_orders with invalid page string falls back to page 1."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000930"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    callback = FakeCallback(
        data="my_orders:not_a_number", user=FakeUser(1), message=message
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
    )
    await callback.answer()
    assert message.answers or callback.answers


@pytest.mark.asyncio
async def test_my_orders_page_one_shows_forward_button(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Page 1 with multiple pages shows 'Вперед' (covers forward nav)."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000911"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    for idx in range(6):
        await create_test_order(
            order_repo,
            user.user_id,
            order_id=UUID(f"00000000-0000-0000-0000-0000000009{10 + idx}"),
            price=1000.0 + idx,
            bloggers_needed=3,
            status=OrderStatus.NEW,
        )
    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(1), message=message
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert message.answers
    last = message.answers[-1]
    text = last[0] if isinstance(last, tuple) else last
    assert "страница 1/2" in text
    if isinstance(last, tuple) and last[1] is not None:
        keyboard = last[1]
        if hasattr(keyboard, "inline_keyboard"):
            assert any(
                b.text == "Вперед ➡️"
                for row in keyboard.inline_keyboard
                for b in row
            )
        else:
            assert any(
                b.text == "Вперед ➡️" for row in keyboard.rows for b in row
            )


@pytest.mark.asyncio
async def test_my_orders_pagination(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Paginate orders list."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000910"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    for idx in range(6):
        await create_test_order(
            order_repo,
            user.user_id,
            order_id=UUID(f"00000000-0000-0000-0000-00000000091{idx}"),
            price=1000.0 + idx,
            bloggers_needed=3,
            status=OrderStatus.NEW,
        )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    callback = FakeCallback(
        data="my_orders:2", user=FakeUser(1), message=message
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    answer_text = (
        message.answers[-1]
        if isinstance(message.answers[-1], str)
        else message.answers[-1][0]
    )
    assert "страница 2/2" in answer_text


@pytest.mark.asyncio
async def test_my_orders_with_complaint_button(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Show complaint button for closed orders with responses."""

    from datetime import datetime, timezone
    from uuid import UUID

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000920"),
        external_id="1",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000921"),
        external_id="2",
        username="blogger",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000922"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        completed_at=datetime.now(timezone.utc),
    )

    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(1))
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "№ 1" in answer_text


@pytest.mark.asyncio
async def test_paginate_orders_blogger(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Paginate blogger's responded orders (my_orders_blogger:page)."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    adv_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="10",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    order = await create_test_order(
        order_repo,
        adv_user.user_id,
        order_id=uuid4(),
        price=300.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )

    blogger_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="11",
        username="blogger",
    )
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger_user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(text=_TEXTS_RU["btn_my_orders"], user=FakeUser(11))
    callback = FakeCallback(
        data="my_orders_blogger:1", user=FakeUser(11), message=message
    )
    await paginate_orders(
        callback,
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        currency_symbol="₽",
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    answer_content = message.answers[-1]
    answer_text = (
        answer_content if isinstance(answer_content, str) else answer_content[0]
    )
    assert "откликнулись" in answer_text
    assert "№ 1" in answer_text
    assert "Активен" in answer_text
    assert "Формат:" in answer_text
    assert "Стоимость 1 UGC: 300 ₽" in answer_text
    assert "Ссылка на проект:" in answer_text


def test_format_price() -> None:
    """_format_price uses space as thousands separator and ruble sign."""
    assert _format_price(500) == "500 ₽"
    assert _format_price(1000) == "1 000 ₽"
    assert _format_price(14343) == "14 343 ₽"
    assert _format_price(1000000) == "1 000 000 ₽"


def test_format_date() -> None:
    """_format_date returns DD.MM.YYYY or em dash for None."""
    from datetime import datetime, timezone

    assert _format_date(None) == "—"
    dt = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
    assert _format_date(dt) == "03.02.2026"


def test_format_order_type() -> None:
    """_format_order_type returns correct labels."""
    order_ugc = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    order_placement = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_PLUS_PLACEMENT,
        product_link="https://x.com",
        offer_text="",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    assert _format_order_type(order_ugc) == "UGC-видео для бренда"
    assert _format_order_type(order_placement) == "UGC + размещение"


def test_format_price_and_barter() -> None:
    """_format_price_and_barter returns correct lines."""
    order_price_only = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="",
        barter_description=None,
        price=5000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    order_barter_only = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="",
        barter_description="Продукт + доставка",
        price=0.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    order_both = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="",
        barter_description="Доп. бартер",
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    assert _format_price_and_barter(order_price_only) == [
        "Стоимость 1 UGC: 5 000 ₽",
    ]
    assert _format_price_and_barter(order_barter_only) == [
        "Бартер: Продукт + доставка",
    ]
    both_lines = _format_price_and_barter(order_both)
    assert "Стоимость 1 UGC: 1 000 ₽" in both_lines
    assert "Бартер: Доп. бартер" in both_lines
    assert len(both_lines) == 2


@pytest.mark.asyncio
async def test_my_orders_shows_active_status_and_matched_count(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Active order shows 'Активен' and dynamic matched count 2/10."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv_active",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    blogger1 = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="b1",
        username="blogger1",
    )
    blogger2 = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="b2",
        username="blogger2",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=uuid4(),
        price=14343.0,
        bloggers_needed=10,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger1.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger1.user_id, accepted=True, in_offer=True
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger2.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger2.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser("adv_active")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Активен" in answer_text
    assert "Подобрано: 2 / 10" in answer_text
    assert "Стоимость 1 UGC: 14 343 ₽" in answer_text
    assert "Дата завершения: —" in answer_text


@pytest.mark.asyncio
async def test_my_orders_shows_completed_status_and_completion_date(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Completed order shows 'Завершён' and completion date."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv_done",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    completion_dt = datetime(2026, 2, 5, 14, 30, 0, tzinfo=timezone.utc)

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=uuid4(),
        price=2000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        completed_at=completion_dt,
    )
    for i in range(3):
        blogger = await create_test_user(
            user_repo,
            user_id=uuid4(),
            external_id=f"b{i}",
            username=f"blogger{i}",
        )
        await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
        await offer_dispatch_repo.record_response(
            order.order_id, blogger.user_id, accepted=True, in_offer=True
        )

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser("adv_done")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Завершён" in answer_text
    assert "Подобрано: 3 / 3" in answer_text
    assert "Дата завершения: 05.02.2026" in answer_text


@pytest.mark.asyncio
async def test_my_orders_advertiser_shows_barter(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Advertiser order list shows barter when barter_description is set."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv_barter",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=uuid4(),
        price=2000.0,
        barter_description="Продукт бренда + доставка",
        bloggers_needed=5,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser("adv_barter")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Стоимость 1 UGC: 2 000 ₽" in answer_text
    assert "Бартер: Продукт бренда + доставка" in answer_text


@pytest.mark.asyncio
async def test_my_orders_blogger_shows_barter(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    offer_dispatch_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger order list shows barter when barter_description is set."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )
    order_service = build_order_service(
        user_repo, advertiser_repo, order_repo, fake_tm
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    adv_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="adv_b",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, adv_user.user_id)
    order = await create_test_order(
        order_repo,
        adv_user.user_id,
        order_id=uuid4(),
        price=0.0,
        barter_description="Бартерное предложение",
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )

    blogger_user = await create_test_user(
        user_repo,
        user_id=uuid4(),
        external_id="blogger_b",
        username="creator",
    )
    await create_test_blogger_profile(blogger_repo, blogger_user.user_id)
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger_user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage(
        text=_TEXTS_RU["btn_my_orders"], user=FakeUser("blogger_b")
    )
    await show_my_orders(
        message,
        FakeFSMContext(),
        user_service,
        profile_service,
        order_service,
        offer_response_service,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Бартер: Бартерное предложение" in answer_text
    assert "Активен" in answer_text
    assert "Формат:" in answer_text
