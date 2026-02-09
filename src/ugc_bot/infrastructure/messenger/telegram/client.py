"""Telegram messenger client implementation."""

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ugc_bot.application.messenger.dto import (
    Button,
    Invoice,
    InvoiceItem,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import MessengerClient


class TelegramMessengerClient(MessengerClient):
    """Messenger client backed by aiogram Bot."""

    def __init__(self, bot: Bot) -> None:
        """Initialize with aiogram Bot."""
        self._bot = bot

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        """Send a text message."""
        await self._bot.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=_build_markup(keyboard),
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview,
        )

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Send a photo message."""
        await self._bot.send_photo(
            chat_id=int(chat_id),
            photo=file_id,
            caption=caption,
            reply_markup=_build_markup(keyboard),
            parse_mode=parse_mode,
        )

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Edit message text."""
        await self._bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=_build_markup(keyboard),
            parse_mode=parse_mode,
        )

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        """Edit message keyboard (or remove)."""
        await self._bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=_build_markup(keyboard),
        )

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Answer a callback query."""
        await self._bot.answer_callback_query(
            callback_query_id=callback_id,
            text=text,
            show_alert=show_alert,
        )

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        """Send invoice for payment."""
        kwargs: dict = {
            "chat_id": int(chat_id),
            "title": invoice.title,
            "description": invoice.description,
            "payload": invoice.payload,
            "provider_token": invoice.provider_token,
            "currency": invoice.currency,
            "prices": [_to_labeled_price(item) for item in invoice.items],
        }
        if invoice.provider_data is not None:
            kwargs["provider_data"] = invoice.provider_data
        await self._bot.send_invoice(**kwargs)


def build_keyboard_markup(keyboard: Keyboard | None):
    """Convert neutral keyboard into aiogram markup."""
    return _build_markup(keyboard)


def _build_markup(keyboard: Keyboard | None):
    """Convert neutral keyboard into aiogram markup."""
    if keyboard is None:
        return None
    if not isinstance(keyboard, Keyboard):
        return keyboard
    if keyboard.kind == KeyboardKind.REMOVE:
        return ReplyKeyboardRemove()
    if keyboard.kind == KeyboardKind.INLINE:
        inline_rows = [
            [_inline_button(btn) for btn in row] for row in keyboard.rows
        ]
        return InlineKeyboardMarkup(inline_keyboard=inline_rows)
    if keyboard.kind == KeyboardKind.REPLY:
        reply_rows = [
            [KeyboardButton(text=btn.text) for btn in row]
            for row in keyboard.rows
        ]
        return ReplyKeyboardMarkup(
            keyboard=reply_rows,
            resize_keyboard=keyboard.resize,
            one_time_keyboard=keyboard.one_time,
            is_persistent=keyboard.is_persistent,
        )
    return None


def _inline_button(button: Button) -> InlineKeyboardButton:
    """Build InlineKeyboardButton from neutral Button."""
    if button.url:
        return InlineKeyboardButton(text=button.text, url=button.url)
    return InlineKeyboardButton(
        text=button.text,
        callback_data=button.callback_data or "",
    )


def _to_labeled_price(item: InvoiceItem):
    """Convert InvoiceItem to aiogram LabeledPrice."""
    from aiogram.types import LabeledPrice

    return LabeledPrice(label=item.label, amount=item.amount_minor)
