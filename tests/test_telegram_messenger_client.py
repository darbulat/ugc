"""Tests for Telegram messenger client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.messenger.dto import (
    Button,
    Invoice,
    InvoiceItem,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
    build_keyboard_markup,
)


@pytest.fixture
def fake_bot() -> MagicMock:
    """Create a fake aiogram Bot that records calls."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()
    bot.answer_callback_query = AsyncMock()
    bot.send_invoice = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_send_photo(fake_bot: MagicMock) -> None:
    """send_photo calls bot.send_photo with correct args."""

    client = TelegramMessengerClient(bot=fake_bot)
    await client.send_photo(
        chat_id="123",
        file_id="file_abc",
        caption="Caption",
    )

    fake_bot.send_photo.assert_called_once_with(
        chat_id=123,
        photo="file_abc",
        caption="Caption",
        reply_markup=None,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_send_photo_with_keyboard(fake_bot: MagicMock) -> None:
    """send_photo passes keyboard markup to bot."""

    client = TelegramMessengerClient(bot=fake_bot)
    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Button", callback_data="cb1")]],
    )
    await client.send_photo(
        chat_id="456",
        file_id="photo_id",
        caption="Caption",
        keyboard=keyboard,
    )

    call_kwargs = fake_bot.send_photo.call_args[1]
    assert call_kwargs["reply_markup"] is not None
    assert call_kwargs["photo"] == "photo_id"


@pytest.mark.asyncio
async def test_edit_text(fake_bot: MagicMock) -> None:
    """edit_text calls bot.edit_message_text."""

    client = TelegramMessengerClient(bot=fake_bot)
    await client.edit_text(
        chat_id="123",
        message_id="42",
        text="New text",
    )

    fake_bot.edit_message_text.assert_called_once_with(
        chat_id=123,
        message_id=42,
        text="New text",
        reply_markup=None,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_edit_reply_markup(fake_bot: MagicMock) -> None:
    """edit_reply_markup calls bot.edit_message_reply_markup."""

    client = TelegramMessengerClient(bot=fake_bot)
    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="X", callback_data="x")]],
    )
    await client.edit_reply_markup(
        chat_id="123",
        message_id="42",
        keyboard=keyboard,
    )

    fake_bot.edit_message_reply_markup.assert_called_once()
    call_kwargs = fake_bot.edit_message_reply_markup.call_args[1]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_answer_callback(fake_bot: MagicMock) -> None:
    """answer_callback calls bot.answer_callback_query."""

    client = TelegramMessengerClient(bot=fake_bot)
    await client.answer_callback(
        callback_id="cb-123",
        text="Done",
        show_alert=True,
    )

    fake_bot.answer_callback_query.assert_called_once_with(
        callback_query_id="cb-123",
        text="Done",
        show_alert=True,
    )


@pytest.mark.asyncio
async def test_send_invoice(fake_bot: MagicMock) -> None:
    """send_invoice calls bot.send_invoice with converted prices."""

    client = TelegramMessengerClient(bot=fake_bot)
    invoice = Invoice(
        title="Invoice",
        description="Test invoice",
        payload="order-123",
        provider_token="token",
        currency="RUB",
        items=[
            InvoiceItem(label="Item 1", amount_minor=10000),
            InvoiceItem(label="Item 2", amount_minor=5000),
        ],
    )
    await client.send_invoice(chat_id="123", invoice=invoice)

    fake_bot.send_invoice.assert_called_once()
    call_kwargs = fake_bot.send_invoice.call_args[1]
    assert call_kwargs["chat_id"] == 123
    assert call_kwargs["title"] == "Invoice"
    assert call_kwargs["currency"] == "RUB"
    assert len(call_kwargs["prices"]) == 2
    assert call_kwargs["prices"][0].label == "Item 1"
    assert call_kwargs["prices"][0].amount == 10000
    assert call_kwargs["prices"][1].label == "Item 2"
    assert call_kwargs["prices"][1].amount == 5000


def test_build_keyboard_markup_inline() -> None:
    """build_keyboard_markup returns InlineKeyboardMarkup for INLINE kind."""

    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Btn", callback_data="cb1")]],
    )
    result = build_keyboard_markup(keyboard)

    assert result is not None
    assert hasattr(result, "inline_keyboard")


def test_build_keyboard_markup_reply() -> None:
    """build_keyboard_markup returns ReplyKeyboardMarkup for REPLY kind."""

    keyboard = Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text="Btn", callback_data=None)]],
        resize=True,
        one_time=True,
    )
    result = build_keyboard_markup(keyboard)

    assert result is not None
    assert hasattr(result, "keyboard")


def test_build_keyboard_markup_remove() -> None:
    """build_keyboard_markup returns ReplyKeyboardRemove for REMOVE kind."""

    keyboard = Keyboard(kind=KeyboardKind.REMOVE, rows=[])
    result = build_keyboard_markup(keyboard)

    assert result is not None
    assert hasattr(result, "remove_keyboard")


def test_build_keyboard_markup_none() -> None:
    """build_keyboard_markup returns None for None input."""

    result = build_keyboard_markup(None)
    assert result is None


def test_build_keyboard_markup_inline_button_with_url() -> None:
    """Inline button with url creates InlineKeyboardButton with url."""

    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Link", url="https://example.com")]],
    )
    result = build_keyboard_markup(keyboard)

    assert result is not None
    assert len(result.inline_keyboard) == 1
    assert len(result.inline_keyboard[0]) == 1
    btn = result.inline_keyboard[0][0]
    assert btn.text == "Link"
    assert btn.url == "https://example.com"


def test_build_keyboard_markup_inline_button_callback_data() -> None:
    """Inline button with callback_data creates InlineKeyboardButton."""

    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Action", callback_data="cb1")]],
    )
    result = build_keyboard_markup(keyboard)

    assert result is not None
    btn = result.inline_keyboard[0][0]
    assert btn.text == "Action"
    assert btn.callback_data == "cb1"


def test_build_keyboard_markup_returns_passthrough_for_non_keyboard() -> None:
    """Non-Keyboard object is returned as-is."""

    custom_markup = object()
    result = build_keyboard_markup(custom_markup)
    assert result is custom_markup


def test_build_keyboard_markup_unknown_kind_returns_none() -> None:
    """Keyboard with unhandled kind returns None (defensive fallback)."""

    # Keyboard with kind that doesn't match REMOVE/INLINE/REPLY
    class UnknownKind:
        def __eq__(self, other: object) -> bool:
            return False

    keyboard = Keyboard(kind=UnknownKind(), rows=[])  # type: ignore[arg-type]
    result = build_keyboard_markup(keyboard)
    assert result is None
