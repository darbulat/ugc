"""Telegram callbacks preserve the same order card and provider boundaries."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.bot.telegram import order_summary_runtime as runtime
from ugc_bot.bot.telegram.handlers.order_summary import (
    decode_id,
    encode_id,
    order_summary_callback,
)
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def screen():
    @asynccontextmanager
    async def transaction():
        yield object()

    order, assignment, draft, customer = (uuid4() for _ in range(4))
    row = dict(
        ordinal=1,
        username="Креатор",
        assignment_id=assignment,
        selection_state="delivered",
        work_state="in_progress",
        report_state=None,
        answer_due_at=None,
        replacement_id=None,
    )
    data = dict(
        order_id=order,
        client_id=customer,
        positions=[row],
        closed=True,
        work_closed=False,
        used=0,
        limit=2,
        draft_id=draft,
        draft={},
        message_id="10",
        message=None,
        reminder=None,
    )
    service = NS(
        view=AsyncMock(return_value=data),
        read=AsyncMock(return_value=data),
        contact=AsyncMock(return_value=(order, "https://example.test/creator")),
        creator_answer=AsyncMock(return_value=True),
        reportable=Mock(return_value=True),
        confirmable=Mock(return_value=True),
        confirmation_key=Mock(return_value="a" * 16),
        record_card_delivery=AsyncMock(),
        summaries=NS(
            forget_message=AsyncMock(),
            claim_message=AsyncMock(return_value=True),
            patch_card=AsyncMock(),
        ),
        transactions=NS(transaction=transaction),
        now=lambda: datetime(2026, 11, 13, tzinfo=UTC),
    )
    telegram = NS(
        send_message=AsyncMock(return_value=NS(message_id=30, chat=NS(id=123)))
    )
    messenger = NS(edit_text=AsyncMock(), answer_callback=AsyncMock())
    users = NS(get_user=AsyncMock(return_value=NS(user_id=customer)))
    return NS(
        service=service,
        telegram=telegram,
        messenger=messenger,
        users=users,
        data=data,
        order=order,
        assignment=assignment,
        draft=draft,
        row=row,
    )


async def click(screen, payload, *, chat="123", message_id="1", text=None):
    incoming = IncomingCallback(
        callback_id="callback",
        chat_id=chat,
        user=IncomingUser(
            external_id="123", messenger_type=MessengerType.TELEGRAM
        ),
        data="os:" + payload,
        message_id=message_id,
        message_text=text,
    )
    await order_summary_callback(
        NS(bot=screen.telegram),
        screen.users,
        screen.service,
        messenger_client=screen.messenger,
        event_adapter=NS(from_callback=lambda _: incoming),
    )


@pytest.mark.asyncio
async def test_card_callback_pages_draft_and_confirmation_use_same_message(
    screen,
):
    order, draft = screen.order.hex, encode_id(screen.draft)
    assignment = encode_id(screen.assignment)
    assert decode_id(assignment) == screen.assignment
    with pytest.raises(ValueError):
        decode_id("invalid")

    screen.data["positions"] *= 6
    screen.data["draft"][str(screen.assignment)] = "refused"
    await click(screen, f"exceptions:{order}:1:1")
    keyboard = screen.messenger.edit_text.await_args.kwargs["keyboard"]
    assert any("✓" in b.text for row in keyboard.rows for b in row)
    assert all(
        len(b.callback_data.encode()) <= 64
        for row in keyboard.rows
        for b in row
    )

    await click(screen, f"pick:{draft}:{assignment}:1")
    args = screen.service.view.await_args
    assert args.args[1] is None
    assert args.kwargs["assignment_id"] == screen.assignment
    assert args.kwargs["reason"] == "refused"
    await click(screen, f"save:{draft}")
    assert screen.service.view.await_args.kwargs["draft_id"] == screen.draft
    await click(screen, f"confirm:{order}")
    assert (
        "Будут подтверждены"
        in screen.messenger.edit_text.await_args.kwargs["text"]
    )
    await click(screen, f"apply:{order}:" + "a" * 16)
    assert screen.service.view.await_args.kwargs["action"] == "confirm"
    assert screen.messenger.edit_text.await_args.kwargs["message_id"] == "10"
    screen.telegram.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_contact_and_withdraw_are_actions_on_existing_card(
    screen,
):
    order, report, replacement = screen.order.hex, uuid4(), uuid4()
    screen.row.update(
        report_state="waiting",
        report_id=report,
        answer_due_at=datetime(2026, 11, 14, tzinfo=UTC),
        replacement_id=replacement,
    )
    await click(screen, f"open:{order}")
    assert (
        "14.11 03:00 МСК"
        in screen.messenger.edit_text.await_args.kwargs["text"]
    )
    await click(screen, f"contact:{replacement.hex}")
    edit = screen.messenger.edit_text.await_args.kwargs
    assert "https://example.test/creator" in edit["text"]
    assert edit["message_id"] == "10"
    await click(screen, f"withdraw:{report.hex}")
    assert screen.service.view.await_args.kwargs["report_id"] == report
    await click(screen, f"remind:{order}")
    keyboard = screen.messenger.edit_text.await_args.kwargs["keyboard"]
    assert any(b.text == "Через 3 дня" for row in keyboard.rows for b in row)
    await click(screen, f"remind3:{order}")
    assert screen.service.view.await_args.kwargs["action"] == "remind3"


@pytest.mark.asyncio
async def test_creator_reply_and_invalid_callbacks_do_not_open_private_card(
    screen,
):
    report = uuid4()
    await click(screen, f"answer:{report.hex}", chat="-44")
    screen.users.get_user.assert_not_awaited()
    await click(screen, f"answer:{report.hex}")
    assert screen.service.creator_answer.await_args.args[1] == report
    assert (
        "Ответ сохранён" in screen.messenger.edit_text.await_args.kwargs["text"]
    )
    screen.service.creator_answer.return_value = False
    await click(screen, f"answer:{report.hex}")
    assert "уже закрыт" in screen.messenger.edit_text.await_args.kwargs["text"]
    await click(screen, f"invalid:{screen.order.hex}")
    assert screen.messenger.answer_callback.await_args.kwargs["show_alert"]
    screen.service.view.assert_not_awaited()


@pytest.mark.asyncio
async def test_recreates_deleted_card_and_adopts_existing_card(
    screen,
):
    method = SendMessage(chat_id=123, text="synthetic")
    screen.messenger.edit_text.side_effect = TelegramBadRequest(
        method=method, message="message to edit not found"
    )
    await click(screen, f"open:{screen.order.hex}")
    screen.service.summaries.forget_message.assert_awaited_once()
    assert screen.telegram.send_message.await_args.kwargs["chat_id"] == 123
    assert screen.service.record_card_delivery.await_args.args[2] == "30"

    screen.data["message_id"] = None
    screen.service.read.return_value = screen.data | {"message_id": "30"}
    screen.messenger.edit_text.side_effect = None
    screen.telegram.send_message.reset_mock()
    await click(
        screen,
        f"open:{screen.order.hex}",
        text=f"Итоги заказа №{screen.order.hex[:8].upper()}\nДанные",
        message_id="30",
    )
    assert screen.messenger.edit_text.await_args.kwargs["message_id"] == "30"
    screen.telegram.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "error", "released"),
    [
        ("missing", "summary_transport_unavailable", False),
        ("claimed", "summary_message_already_claimed", False),
        ("forbidden", "summary_transport_rejected", True),
        ("timeout", "summary_transport_unknown", False),
        ("wrong_chat", "summary_transport_unknown", False),
    ],
)
async def test_card_sending_never_repeats_uncertain_delivery(
    screen, scenario, error, released
):
    bot = screen.telegram
    method = SendMessage(chat_id=123, text="synthetic")
    if scenario == "missing":
        bot = None
    elif scenario == "claimed":
        screen.service.summaries.claim_message.return_value = False
    elif scenario == "forbidden":
        bot.send_message.side_effect = TelegramForbiddenError(
            method=method, message="blocked"
        )
    elif scenario == "timeout":
        bot.send_message.side_effect = TimeoutError
    else:
        bot.send_message.return_value = NS(message_id=30, chat=NS(id=999))
    with pytest.raises(ValueError, match=error):
        await runtime.send_card(
            screen.service, screen.data, "card", None, "123", bot
        )
    assert screen.service.summaries.patch_card.await_count == int(released)
    assert screen.telegram.send_message.await_count <= 1
    screen.service.record_card_delivery.assert_not_awaited()
