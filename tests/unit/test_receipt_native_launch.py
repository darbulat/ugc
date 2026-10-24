"""Native launch payloads at provider boundaries, without financial fake IDs."""

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.unit.test_notice_receipt_adapters import MaxSession
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    TelegramNoticeReceipts,
)


@dataclass(frozen=True)
class Message:
    channel: str | None
    address: str | None
    address_kind: str = "chat_id"
    text: str = "Real stored proof contains https://unrelated.example.test/"
    action_url: str | None = None
    action_label: str | None = None


def telegram():
    return SimpleNamespace(
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                message_id=17, chat=SimpleNamespace(id=101)
            )
        )
    )


URL = "https://app.example.test/miniapp/app.html?assignment=real-assignment"


@pytest.mark.asyncio
async def test_telegram_uses_explicit_stored_web_app_action_not_a_text_link():
    bot = telegram()
    message = Message("telegram", "101", action_url=URL, action_label="Открыть")
    receipt = await TelegramNoticeReceipts(bot).send(message)
    assert receipt.reference == "101:17"
    assert bot.send_message.await_count == 1
    request = bot.send_message.call_args.kwargs
    assert request["text"] == message.text and request["parse_mode"] is None
    button = request["reply_markup"].inline_keyboard[0][0]
    assert button.model_dump(exclude_none=True) == {
        "text": "Открыть",
        "web_app": {"url": URL},
    }


@pytest.mark.asyncio
async def test_max_uses_open_app_field_in_one_inline_keyboard_attachment():
    session = MaxSession()
    message = Message(
        "max", "202", "user_id", action_url=URL, action_label="Open"
    )
    receipt = await MaxNoticeReceipts(session, "synthetic").send(message)
    assert receipt.reference == "mid.actual.12" and len(session.calls) == 1
    assert session.calls[0][1]["json"] == {
        "text": message.text,
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [{"type": "open_app", "text": "Open", "web_app": URL}]
                    ]
                },
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
async def test_generic_message_with_no_action_sends_without_financial_ids(
    channel,
):
    message = Message(channel, "101")
    bot, session = telegram(), MaxSession()
    adapter = (
        TelegramNoticeReceipts(bot)
        if channel == "telegram"
        else MaxNoticeReceipts(session, "synthetic")
    )
    await adapter.send(message)
    if channel == "telegram":
        assert bot.send_message.call_args.kwargs == {
            "chat_id": 101,
            "text": message.text,
            "parse_mode": None,
        }
    else:
        assert session.calls[0][1]["json"] == {"text": message.text}


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
@pytest.mark.parametrize(
    "url,label",
    [
        (URL, None),
        (None, "Open"),
        ("", "Open"),
        ("http://app.example.test/", "Open"),
        ("https://user:password@app.example.test/", "Open"),
        ("javascript:alert(1)", "Open"),
        (URL, "  "),
        (URL, "Open\napp"),
    ],
)
async def test_invalid_action_is_definite_failure_without_external_io(
    channel, url, label
):
    bot, session = telegram(), MaxSession()
    adapter = (
        TelegramNoticeReceipts(bot)
        if channel == "telegram"
        else MaxNoticeReceipts(session, "synthetic")
    )
    with pytest.raises(DeliveryFailure) as failure:
        await adapter.send(
            Message(channel, "101", action_url=url, action_label=label)
        )
    assert not failure.value.uncertain
    assert not bot.send_message.called and not session.calls


@pytest.mark.asyncio
async def test_telegram_native_launch_is_rejected_for_a_group_before_io():
    bot = telegram()
    with pytest.raises(DeliveryFailure) as failure:
        await TelegramNoticeReceipts(bot).send(
            Message("telegram", "-100101", action_url=URL, action_label="Open")
        )
    assert not failure.value.uncertain and not bot.send_message.called
