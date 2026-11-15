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


@pytest.fixture
def private_invite_chat(monkeypatch):
    from aiogram.types import Chat, Message, User

    answer = AsyncMock()
    edit = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)
    monkeypatch.setattr(Message, "edit_text", edit)

    def make(*, private=True):
        return Message.model_construct(
            chat=Chat(id=100 if private else 200, type="private"),
            from_user=User(id=100, first_name="Test", is_bot=False),
        )

    return make, answer, edit


@pytest.mark.asyncio
async def test_order_link_shows_only_the_owned_preview_or_real_summary(
    private_invite_chat,
):
    from aiogram.filters import CommandObject

    from ugc_bot.bot.telegram.handlers.creator_invites import open_invite_order

    make, answer, _ = private_invite_chat
    order, owner = uuid4(), uuid4()
    command = CommandObject(args=f"ir_{order.hex}")
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id=owner))
    )
    service = SimpleNamespace(preview_card=AsyncMock(return_value=[]))
    summary = SimpleNamespace(view=AsyncMock())
    await open_invite_order(
        make(private=False), command, roles, service, summary
    )
    roles.get_user.assert_not_awaited()
    await open_invite_order(make(), command, roles, service, summary)
    keyboard = answer.call_args.kwargs["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data == f"ip:{order.hex}"
    summary.view.assert_not_awaited()

    service.preview_card.side_effect = PermissionError
    await open_invite_order(make(), command, roles, service, summary)
    assert summary.view.call_args.args[0].user_id == owner
    keyboard = answer.call_args.kwargs["reply_markup"].inline_keyboard
    assert keyboard[0][0].callback_data != f"ip:{order.hex}"
    summary.view.side_effect = PermissionError
    await open_invite_order(make(), command, roles, service, summary)
    assert answer.call_args.args == ("Заказ недоступен.",)

    roles.get_user.return_value = None
    answer.reset_mock()
    await open_invite_order(make(), command, roles, service, summary)
    answer.assert_not_awaited()
    await open_invite_order(make(), command, roles, service)
    answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_sharing_is_private_and_changes_only_for_the_authenticated_order(
    private_invite_chat,
):
    from ugc_bot.bot.telegram.handlers.creator_invites import (
        change_invite_sharing,
    )

    make, _, _ = private_invite_chat
    order, owner = uuid4(), uuid4()
    user = FakeUser(100, "owner")
    roles = SimpleNamespace(get_user=AsyncMock(return_value=None))
    service = SimpleNamespace(client_sharing=AsyncMock())
    callback = FakeCallback(f"ic:{order.hex}:1", user, make(private=False))
    await change_invite_sharing(callback, roles, service)
    roles.get_user.assert_not_awaited()
    callback.message = make()
    await change_invite_sharing(callback, roles, service)
    assert callback.answers[-1] == "Заказ недоступен."
    service.client_sharing.assert_not_awaited()

    roles.get_user.return_value = SimpleNamespace(user_id=owner)
    service.client_sharing.side_effect = PermissionError
    await change_invite_sharing(callback, roles, service)
    assert callback.answers[-1] == "Заказ недоступен."
    service.client_sharing.side_effect = ValueError
    await change_invite_sharing(callback, roles, service)
    assert "@username" in callback.answers[-1]
    service.client_sharing.side_effect = None
    await change_invite_sharing(callback, roles, service)
    principal, selected_order, enabled = service.client_sharing.call_args.args
    assert (principal.user_id, selected_order, enabled) == (owner, order, True)
    callback.data = f"ic:{order.hex}:0"
    await change_invite_sharing(callback, roles, service)
    assert service.client_sharing.call_args.args[-1] is False
    assert callback.answers[-1] == "Ваш Telegram скрыт."


@pytest.mark.asyncio
async def test_creator_reply_failure_does_not_prevent_the_customer_notice(
    private_invite_chat, monkeypatch
):
    make, answer, _ = private_invite_chat
    order, invite, creator = uuid4(), uuid4(), uuid4()
    bot = SimpleNamespace(send_message=AsyncMock())
    callback = FakeCallback(
        f"oi:oi_{invite.hex}", FakeUser(100), make(), bot=bot
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id=creator))
    )
    service = SimpleNamespace(
        accept=AsyncMock(),
        creator_contact=AsyncMock(return_value=("Заказчик", "@owner")),
        claim_manager_notice=AsyncMock(side_effect=[(200, order, 1), None]),
    )
    notice = AsyncMock()
    monkeypatch.setattr(
        "ugc_bot.application.services.invite_handoff_notices.deliver_invite_notice",
        notice,
    )
    await accept_creator_invite(callback, roles, service)
    answer.assert_awaited_once_with("Заказчик · @owner", parse_mode=None)
    notice.assert_awaited_once_with(service, bot, invite, "customer")

    answer.side_effect = TimeoutError
    await accept_creator_invite(callback, roles, service)
    assert notice.await_count == 2
    bot.send_message.assert_awaited_once()
