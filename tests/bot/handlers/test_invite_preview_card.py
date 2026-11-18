"""The Telegram test card discloses contacts only in the owner's chat."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.types import Chat, Message, User

from ugc_bot.bot.telegram.handlers.creator_invites import (
    open_preview_card,
    refresh_preview_card,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
)


@pytest.mark.asyncio
async def test_test_card_opens_and_refreshes_only_for_its_owner(monkeypatch):
    send, edit = AsyncMock(), AsyncMock()
    monkeypatch.setattr(Message, "answer", send)
    monkeypatch.setattr(Message, "edit_text", edit)
    order_id, owner = uuid4(), uuid4()
    message = Message(
        message_id=33,
        date=datetime.now(timezone.utc),
        chat=Chat(id=100, type="private"),
        from_user=User(id=100, is_bot=False, first_name="Клиент"),
    )
    command = CommandObject(command="start", args="ip_" + order_id.hex)
    roles = SimpleNamespace(get_user=AsyncMock(return_value=None))
    rows = [
        SimpleNamespace(ordinal=1, telegram=None),
        SimpleNamespace(
            ordinal=2,
            telegram="creator",
            instagram="creator",
            creator_name="Креатор",
            consent_source=PREVIEW_CONSENT,
        ),
        SimpleNamespace(
            ordinal=3,
            telegram="manual",
            instagram="manual",
            creator_name=None,
            consent_source="instagram",
        ),
    ]
    service = SimpleNamespace(preview_card=AsyncMock(return_value=rows))
    await open_preview_card(message, command, roles)
    assert send.call_args.args == ("Предпросмотр заказа недоступен.",)
    await open_preview_card(message, command, roles, service)
    assert send.call_args.args == ("Предпросмотр заказа недоступен.",)
    service.preview_card.assert_not_awaited()

    roles.get_user.return_value = SimpleNamespace(user_id=owner)
    await open_preview_card(message, command, roles, service)
    text = send.call_args.args[0]
    assert "№1 · Ожидает контакта" in text
    assert "Подтверждено в боте" in text and "@creator" in text
    assert "Согласие получено в переписке" in text and "@manual" in text
    principal, actual_order = service.preview_card.call_args.args
    assert (principal.user_id, principal.external_id, actual_order) == (
        owner,
        "100",
        order_id,
    )

    callback = SimpleNamespace(
        data="ip:" + order_id.hex,
        message=message,
        from_user=message.from_user,
        answer=AsyncMock(),
    )
    await refresh_preview_card(callback, roles, service)
    assert edit.call_args.args[0] == text
    edit.side_effect = TelegramBadRequest(
        method=None, message="message is not modified"
    )
    await refresh_preview_card(callback, roles, service)
    edit.side_effect = TelegramBadRequest(
        method=None, message="message cannot be edited"
    )
    with pytest.raises(TelegramBadRequest):
        await refresh_preview_card(callback, roles, service)
    service.preview_card.side_effect = PermissionError
    await refresh_preview_card(callback, roles, service)
    assert callback.answer.call_args.kwargs == {"show_alert": True}
    outsider = message.model_copy(update={"chat": Chat(id=101, type="private")})
    callback.message = outsider
    await refresh_preview_card(callback, roles, service)
    assert not callback.answer.call_args.args
    await open_preview_card(outsider, command, roles, service)
    assert send.await_count == 3
