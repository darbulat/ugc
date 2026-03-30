"""Tests for Telegram support group reply handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.bot.telegram.handlers.support_chat import (
    handle_support_group_reply,
)


def _make_config(support_chat_id: str = "-100123456"):
    cfg = MagicMock()
    cfg.market.support_chat_id = support_chat_id
    return cfg


def _make_bot_texts_service():
    svc = AsyncMock()
    svc.get = AsyncMock(return_value=None)
    return svc


def _make_message(
    chat_id: int = -100123456,
    chat_type: str = "supergroup",
    reply_to_message_id: int | None = 42,
    text: str = "Here is the answer",
):
    message = AsyncMock()
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.chat.type = chat_type
    message.text = text
    if reply_to_message_id is not None:
        reply_msg = MagicMock()
        reply_msg.message_id = reply_to_message_id
        message.reply_to_message = reply_msg
    else:
        message.reply_to_message = None
    return message


@pytest.mark.asyncio
async def test_reply_forwarded_to_max_user():
    config = _make_config()
    support_service = AsyncMock()
    support_service.find_user_by_support_reply = AsyncMock(
        return_value="max_chat_100"
    )
    max_client = AsyncMock()
    message = _make_message()

    await handle_support_group_reply(
        message=message,
        config=config,
        support_service=support_service,
        bot_texts_service=_make_bot_texts_service(),
        max_messenger_client=max_client,
    )

    support_service.find_user_by_support_reply.assert_called_once_with(42)
    max_client.send_text.assert_called_once()
    call_kwargs = max_client.send_text.call_args.kwargs
    assert call_kwargs["chat_id"] == "max_chat_100"
    assert "Here is the answer" in call_kwargs["text"]
    message.reply.assert_called_once()


@pytest.mark.asyncio
async def test_reply_unknown_message_id():
    config = _make_config()
    support_service = AsyncMock()
    support_service.find_user_by_support_reply = AsyncMock(return_value=None)
    max_client = AsyncMock()
    message = _make_message()

    await handle_support_group_reply(
        message=message,
        config=config,
        support_service=support_service,
        bot_texts_service=_make_bot_texts_service(),
        max_messenger_client=max_client,
    )

    max_client.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_reply_wrong_chat_id():
    config = _make_config(support_chat_id="-999")
    support_service = AsyncMock()
    max_client = AsyncMock()
    message = _make_message(chat_id=-100123456)

    await handle_support_group_reply(
        message=message,
        config=config,
        support_service=support_service,
        bot_texts_service=_make_bot_texts_service(),
        max_messenger_client=max_client,
    )

    support_service.find_user_by_support_reply.assert_not_called()


@pytest.mark.asyncio
async def test_reply_no_max_client():
    config = _make_config()
    support_service = AsyncMock()
    support_service.find_user_by_support_reply = AsyncMock(
        return_value="max_chat_100"
    )
    message = _make_message()

    await handle_support_group_reply(
        message=message,
        config=config,
        support_service=support_service,
        bot_texts_service=_make_bot_texts_service(),
        max_messenger_client=None,
    )

    # Should not crash, just log error


@pytest.mark.asyncio
async def test_reply_no_support_chat_configured():
    config = _make_config(support_chat_id="")
    support_service = AsyncMock()
    max_client = AsyncMock()
    message = _make_message()

    await handle_support_group_reply(
        message=message,
        config=config,
        support_service=support_service,
        bot_texts_service=_make_bot_texts_service(),
        max_messenger_client=max_client,
    )

    support_service.find_user_by_support_reply.assert_not_called()
