"""Tests for messenger context adapters."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.messenger.context import (
    CallbackContext,
    MessageContext,
)
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def mock_messenger_client() -> MagicMock:
    """Mock messenger client for context tests."""
    client = MagicMock()
    client.send_text = AsyncMock()
    client.edit_text = AsyncMock()
    client.edit_reply_markup = AsyncMock()
    client.answer_callback = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_message_context_edit_text_skips_when_no_message_id(
    mock_messenger_client: MagicMock,
) -> None:
    """edit_text returns early when message_id is None."""
    incoming = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        text="hi",
        message_id=None,
    )
    ctx = MessageContext(incoming, mock_messenger_client)

    await ctx.edit_text("updated")

    mock_messenger_client.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_message_context_edit_text_when_message_id_set(
    mock_messenger_client: MagicMock,
) -> None:
    """edit_text calls messenger when message_id is set."""
    incoming = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        text="hi",
        message_id="456",
    )
    ctx = MessageContext(incoming, mock_messenger_client)

    await ctx.edit_text("updated")

    mock_messenger_client.edit_text.assert_called_once_with(
        chat_id="123",
        message_id="456",
        text="updated",
        keyboard=None,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_message_context_edit_reply_markup_skips_when_no_message_id(
    mock_messenger_client: MagicMock,
) -> None:
    """edit_reply_markup returns early when message_id is None."""
    incoming = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        text="hi",
        message_id=None,
    )
    ctx = MessageContext(incoming, mock_messenger_client)

    await ctx.edit_reply_markup(reply_markup=MagicMock())

    mock_messenger_client.edit_reply_markup.assert_not_called()


@pytest.mark.asyncio
async def test_message_context_edit_reply_markup_when_message_id_set(
    mock_messenger_client: MagicMock,
) -> None:
    """edit_reply_markup calls messenger when message_id is set."""
    incoming = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        text="hi",
        message_id="456",
    )
    ctx = MessageContext(incoming, mock_messenger_client)
    markup = MagicMock()

    await ctx.edit_reply_markup(reply_markup=markup)

    mock_messenger_client.edit_reply_markup.assert_called_once_with(
        chat_id="123",
        message_id="456",
        keyboard=markup,
    )


@pytest.mark.asyncio
async def test_callback_context_answer(
    mock_messenger_client: MagicMock,
) -> None:
    """CallbackContext.answer calls answer_callback."""
    incoming = IncomingCallback(
        callback_id="cb1",
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        data="feedback:adv:abc:ok",
        message_id="456",
    )
    ctx = CallbackContext(incoming, mock_messenger_client)

    await ctx.answer("Done", show_alert=True)

    mock_messenger_client.answer_callback.assert_called_once_with(
        callback_id="cb1",
        text="Done",
        show_alert=True,
    )
