"""Telegram acceptance keeps invitation details and notifications scoped."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest

from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.bot.telegram.handlers.creator_invites import (
    CardContactTransport,
    accept_creator_invite,
    show_invite,
)


@pytest.mark.asyncio
async def test_invite_link_shows_current_order_and_consent_state():
    user = FakeUser(100, "creator")
    message = FakeMessage(user=user)
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id="creator"))
    )
    order, identity = uuid4(), uuid4()
    payload = f"oi_{identity.hex}"
    row = {
        "order_id": order,
        "status": "active",
        "consented_at": None,
        "reported_at": object(),
        "offer_text": "Тренировка по сквошу",
        "geography": "Казань",
        "instagram": "creator",
    }
    service = SimpleNamespace(
        open_invite=AsyncMock(return_value=row),
        creator_contact=AsyncMock(return_value=None),
    )

    await show_invite(message, roles, service, "invalid")
    assert "Приглашение недоступно" in message.answers[-1]
    service.open_invite.assert_not_awaited()
    await show_invite(message, roles, service, payload)
    service.open_invite.assert_awaited_once_with(identity, "creator")
    text, markup = message.answers[-1]
    assert all(
        piece in text
        for piece in (
            "Тренировка по сквошу",
            "Казань",
            "@creator",
            "уже отметил ваше согласие",
        )
    )
    assert markup.inline_keyboard[0][0].callback_data == f"oi:{payload}"
    row["status"] = "closed"
    await show_invite(message, roles, service, payload)
    assert "Заказ закрыт" in message.answers[-1]
    row["consented_at"] = object()
    await show_invite(message, roles, service, payload)
    assert "уже подтвердили участие" in message.answers[-2]


@pytest.mark.asyncio
async def test_acceptance_notifies_only_assigned_manager_once():
    creator = FakeUser(100, "creator")
    message = FakeMessage(user=creator)
    bot = SimpleNamespace(send_message=AsyncMock())
    identity, order = uuid4(), uuid4()
    callback = FakeCallback(f"oi:oi_{identity.hex}", creator, message, bot=bot)
    roles = SimpleNamespace(get_user=AsyncMock(return_value=None))
    service = SimpleNamespace(
        accept=AsyncMock(),
        claim_manager_notice=AsyncMock(side_effect=[(200, order, 3), None]),
    )
    await accept_creator_invite(callback, roles, service)
    assert "заполните анкету" in callback.answers[-1]
    service.accept.assert_not_awaited()
    roles.get_user.return_value = SimpleNamespace(user_id="creator")
    original_message = callback.message
    callback.message = FakeMessage(user=FakeUser(101))
    await accept_creator_invite(callback, roles, service)
    assert callback.answers[-1] == "Приглашение недоступно."
    callback.message = original_message

    service.accept.side_effect = ValueError("creator_invite_instagram_mismatch")
    await accept_creator_invite(callback, roles, service)
    assert "Подтвердите Instagram" in callback.answers[-1]
    service.claim_manager_notice.assert_not_awaited()
    service.accept.side_effect = None
    await accept_creator_invite(callback, roles, service)
    assert callback.answers[-1] == "Участие подтверждено."
    assert bot.send_message.call_args.kwargs["chat_id"] == 200
    assert "позиция №3" in bot.send_message.call_args.kwargs["text"]
    await accept_creator_invite(callback, roles, service)
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_notice_timeout_does_not_retry_or_reject_the_creator():
    creator = FakeUser(100, "creator")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError))
    identity, order = uuid4(), uuid4()
    callback = FakeCallback(
        f"oi:oi_{identity.hex}", creator, FakeMessage(user=creator), bot=bot
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id="creator"))
    )
    service = SimpleNamespace(
        accept=AsyncMock(),
        claim_manager_notice=AsyncMock(side_effect=[(200, order, 3), None]),
    )

    await accept_creator_invite(callback, roles, service)
    await accept_creator_invite(callback, roles, service)

    assert callback.answers == ["Участие подтверждено."] * 2
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_contact_edits_only_the_customers_existing_card():
    messenger = SimpleNamespace(edit_text=AsyncMock(), send_text=AsyncMock())
    transport = CardContactTransport(messenger, "200", "412", "Итоги", [])
    attempt = SimpleNamespace(
        channel="telegram",
        address="201",
        text="@external",
        interest_id="interest",
    )
    with pytest.raises(DeliveryFailure, match="card_address_changed"):
        await transport.send(attempt)
    messenger.edit_text.assert_not_awaited()
    attempt.address = "200"
    assert (await transport.send(attempt)).channel == "telegram"
    messenger.edit_text.assert_awaited_once_with(
        chat_id="200", message_id="412", text="Итоги\n\n@external", keyboard=[]
    )
    messenger.edit_text.side_effect = TelegramBadRequest(
        method=None, message="message is not modified"
    )
    await transport.send(attempt)
    messenger.edit_text.side_effect = TelegramBadRequest(
        method=None, message="message to edit not found"
    )
    with pytest.raises(TelegramBadRequest, match="not found"):
        await transport.send(attempt)
    messenger.send_text.assert_not_awaited()
