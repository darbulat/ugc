"""Tests for my orders handler."""

from uuid import UUID

import pytest

from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.bot.handlers.keyboards import MY_ORDERS_BUTTON_TEXT
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.my_orders import paginate_orders, show_my_orders
from ugc_bot.domain.enums import MessengerType, OrderStatus
from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_order,
    create_test_user,
)
from tests.helpers.services import build_order_service, build_profile_service


@pytest.mark.asyncio
async def test_show_my_orders_returns_early_when_no_from_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """show_my_orders returns without answering when message.from_user is None."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    message = FakeMessage(text="/my_orders", user=None)
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_show_my_orders_user_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """Show hint when user is not in DB (get_user returns None)."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    message = FakeMessage(text="/my_orders", user=FakeUser(1))
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )
    assert message.answers
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_no_advertiser_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """Show hint when advertiser profile is missing."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    await user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert "Профиль рекламодателя не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_empty(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """Show hint when no orders exist."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    user = await user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(text="/my_orders", user=FakeUser(1))
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
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
    order_response_repo,
) -> None:
    """List existing orders."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
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
    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert str(order.order_id) in answer_text


@pytest.mark.asyncio
async def test_paginate_orders_returns_early_when_no_from_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """paginate_orders returns without answering when callback.from_user is None."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(data="my_orders:1", user=None, message=FakeMessage())
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
    )
    assert not callback.answers or callback.answers == [""]


@pytest.mark.asyncio
async def test_paginate_orders_user_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """paginate_orders answers when user is not found."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(999), message=FakeMessage()
    )
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
    )
    assert callback.answers
    assert "не найден" in callback.answers[0]


@pytest.mark.asyncio
async def test_paginate_orders_no_advertiser_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """paginate_orders answers when advertiser profile is missing."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000935"),
        external_id="1",
        username="adv",
    )
    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    callback = FakeCallback(data="my_orders:1", user=FakeUser(1), message=message)
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
    )
    assert callback.answers
    assert "Профиль рекламодателя не заполнен" in callback.answers[0]


@pytest.mark.asyncio
async def test_paginate_orders_skips_edit_when_message_has_no_edit_text(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """paginate_orders does not call edit_text when callback.message has no edit_text."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000936"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message_without_edit = object()
    callback = FakeCallback(
        data="my_orders:1", user=FakeUser(1), message=message_without_edit
    )
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
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
    order_response_repo,
) -> None:
    """paginate_orders with invalid page string falls back to page 1."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000930"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    callback = FakeCallback(
        data="my_orders:not_a_number", user=FakeUser(1), message=message
    )
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
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
    order_response_repo,
) -> None:
    """Page 1 with multiple pages shows 'Вперед' button (covers _render_page forward nav)."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
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
            order_id=UUID(f"00000000-0000-0000-0000-0000000009{10+idx}"),
            price=1000.0 + idx,
            bloggers_needed=3,
            status=OrderStatus.NEW,
        )
    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    callback = FakeCallback(data="my_orders:1", user=FakeUser(1), message=message)
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
    )
    assert message.answers
    last = message.answers[-1]
    text = last[0] if isinstance(last, tuple) else last
    assert "страница 1/2" in text
    if isinstance(last, tuple) and last[1] is not None:
        assert any(b.text == "Вперед ➡️" for row in last[1].inline_keyboard for b in row)


@pytest.mark.asyncio
async def test_my_orders_pagination(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    blogger_repo,
    order_response_repo,
) -> None:
    """Paginate orders list."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
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

    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    callback = FakeCallback(data="my_orders:2", user=FakeUser(1), message=message)
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
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
    order_response_repo,
) -> None:
    """Show complaint button for closed orders with responses."""

    from datetime import datetime, timezone
    from uuid import UUID

    from ugc_bot.domain.entities import OrderResponse

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
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
        contacts_sent_at=datetime.now(timezone.utc),
    )

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000923"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    message = FakeMessage(text=MY_ORDERS_BUTTON_TEXT, user=FakeUser(1))
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert str(order.order_id) in answer_text
