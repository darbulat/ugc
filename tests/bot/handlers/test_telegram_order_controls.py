"""Telegram cancellation and order-specific payment help."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.helpers.factories import create_test_order
from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeUser,
)
from ugc_bot.bot.telegram.handlers.my_orders import (
    _render_page,
    cancel_order_callback,
)
from ugc_bot.bot.telegram.handlers.order_controls import (
    CANCEL_ORDER_PREFIX,
    CONFIRM_CANCEL_ORDER_PREFIX,
    payment_help_button,
)
from ugc_bot.bot.telegram.handlers.order_creation import (
    handle_customer_problem,
    handle_customer_problem_reason,
)
from ugc_bot.domain.enums import OrderStatus


@pytest.mark.asyncio
async def test_only_new_orders_show_cancel_and_payment_help(order_repo):
    user_id = uuid4()
    orders = [
        await create_test_order(order_repo, user_id, status=status)
        for status in (OrderStatus.NEW, OrderStatus.ACTIVE, OrderStatus.CLOSED)
    ]
    response_service = SimpleNamespace(count_by_order=AsyncMock(return_value=0))
    cancellation = SimpleNamespace(
        cancelled_orders=AsyncMock(return_value={orders[-1].order_id})
    )
    text, keyboard = await _render_page(
        orders, 1, response_service, cancellation=cancellation
    )
    callbacks = {b.callback_data for row in keyboard.rows for b in row}
    assert "Отменён" in text
    assert callbacks == {
        f"pay_order:{orders[0].order_id}",
        f"{CANCEL_ORDER_PREFIX}{orders[0].order_id}",
        payment_help_button(orders[0].order_id, "ru").callback_data,
    }


@pytest.mark.asyncio
async def test_cancel_prompts_then_shows_payment_help_when_checkout_wins(
    messenger_client, event_adapter
):
    user, order_id = FakeUser(112233), uuid4()
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id=uuid4()))
    )
    cancellation = SimpleNamespace(
        cancel=AsyncMock(side_effect=["confirm", "processing"])
    )
    message = FakeMessage(user=user)
    for prefix in (CANCEL_ORDER_PREFIX, CONFIRM_CANCEL_ORDER_PREFIX):
        await cancel_order_callback(
            FakeCallback(f"{prefix}{order_id}", user, message),
            roles,
            cancellation,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
    initial = messenger_client.sent_text[-1]["keyboard"]
    assert (
        initial.rows[0][0].callback_data
        == f"{CONFIRM_CANCEL_ORDER_PREFIX}{order_id}"
    )
    updated = messenger_client.edited_text[-1]
    assert "обрабатывается" in updated["text"]
    assert updated["keyboard"].rows[0][0] == payment_help_button(order_id, "ru")
    assert [
        call.kwargs["confirm"] for call in cancellation.cancel.await_args_list
    ] == [False, True]


@pytest.mark.asyncio
async def test_payment_help_reuses_order_and_telegram_contact(
    messenger_client, event_adapter
):
    user, user_id, order_id = FakeUser(112233, "client"), uuid4(), uuid4()
    roles = SimpleNamespace(
        get_user=AsyncMock(
            return_value=SimpleNamespace(user_id=user_id, language="ru")
        )
    )
    orders = SimpleNamespace(
        get_order=AsyncMock(return_value=SimpleNamespace(advertiser_id=user_id))
    )
    support = SimpleNamespace(
        create_payment_request=AsyncMock(return_value={"number": "123"})
    )
    state = FakeFSMContext()
    await handle_customer_problem(
        FakeCallback(
            payment_help_button(order_id, "ru").callback_data,
            user,
            FakeMessage(user=user),
        ),
        state,
        roles,
        orders,
        messenger_client,
        event_adapter,
    )
    assert order_id.hex[:8].upper() in messenger_client.sent_text[-1]["text"]
    await handle_customer_problem_reason(
        FakeMessage(text="Не открывается счёт", user=user),
        state,
        roles,
        support,
        messenger_client,
        event_adapter,
    )
    command = support.create_payment_request.await_args.args[1]
    assert command.order_id == order_id
    assert command.reason == "Не открывается счёт"
    assert command.contact_reference == "@client"
    assert "123" in messenger_client.sent_text[-1]["text"]
    assert await state.get_state() is None
