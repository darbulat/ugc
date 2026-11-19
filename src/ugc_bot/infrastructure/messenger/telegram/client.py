"""Telegram messenger client implementation."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.types import (
    BufferedInputFile,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from ugc_bot.application.creator_offer_cards import NEUTRAL_COVER, OfferCard
from ugc_bot.application.messenger.dto import (
    Button,
    Invoice,
    InvoiceItem,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.infrastructure.messenger.telegram.offer_cover import (
    neutral_offer_cover,
)
from ugc_bot.infrastructure.order_images import telegram_order_photo

TELEGRAM_API_RETRY_ATTEMPTS = 3
TELEGRAM_API_RETRY_DELAY_SECONDS = 0.5

T = TypeVar("T")
logger = logging.getLogger(__name__)


def is_user_blocked_bot(exc: BaseException) -> bool:
    """True if user is unreachable and retries are pointless."""
    from ugc_bot.infrastructure.messenger.max.client import (
        MaxChatNotFoundError,
        MaxUserBlockedError,
    )

    if isinstance(
        exc, (TelegramForbiddenError, MaxUserBlockedError, MaxChatNotFoundError)
    ):
        return True
    if isinstance(exc, TelegramBadRequest):
        msg = (getattr(exc, "message", None) or str(exc)).lower()
        return "blocked" in msg
    return False


class TelegramMessengerClient(MessengerClient):
    """Messenger client backed by aiogram Bot with retry on network errors."""

    def __init__(
        self,
        bot: Bot,
        *,
        retry_attempts: int = TELEGRAM_API_RETRY_ATTEMPTS,
        retry_delay_seconds: float = TELEGRAM_API_RETRY_DELAY_SECONDS,
        on_confirmed_block: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize with aiogram Bot and optional retry parameters."""
        self._bot = bot
        self._retry_attempts = retry_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._on_confirmed_block = on_confirmed_block

    async def _with_retry(
        self, coro_factory: Callable[[], Awaitable[T]], *, chat_id: str = ""
    ) -> T:
        """Execute coroutine with retry on TelegramNetworkError only.

        Do not retry when user blocked the bot (TelegramForbiddenError or
        TelegramBadRequest with 'blocked' in message).
        """
        last_exc: TelegramNetworkError | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await coro_factory()
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                if (
                    self._on_confirmed_block is not None
                    and chat_id.isdecimal()
                    and "bot was blocked by the user" in exc.message.lower()
                ):
                    try:
                        await self._on_confirmed_block(chat_id)
                    except Exception:
                        logger.error("Telegram send refusal was not saved")
                raise
            except TelegramNetworkError as exc:
                last_exc = exc
                if attempt < self._retry_attempts:
                    await asyncio.sleep(self._retry_delay_seconds)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            "Retry loop finished without attempt"
        )  # pragma: no cover

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
        await self._with_retry(
            lambda: self._bot.send_message(
                chat_id=int(chat_id),
                text=text,
                reply_markup=_build_markup(keyboard),
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview,
            ),
            chat_id=chat_id,
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
        await self._with_retry(
            lambda: self._bot.send_photo(
                chat_id=int(chat_id),
                photo=telegram_order_photo(file_id),
                caption=caption,
                reply_markup=_build_markup(keyboard),
                parse_mode=parse_mode,
            ),
            chat_id=chat_id,
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
        try:
            await self._with_retry(
                lambda: self._bot.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    text=text,
                    reply_markup=_build_markup(keyboard),
                    parse_mode=parse_mode,
                )
            )
        except TelegramBadRequest as exc:
            msg = (getattr(exc, "message", None) or str(exc)).lower()
            if "message is not modified" not in msg:
                raise

    async def send_offer_card(
        self, chat_id: str, card: OfferCard, cover: str | None
    ) -> str:
        if cover is None:
            message = await self._bot.send_message(
                chat_id=int(chat_id),
                text=card.text,
                reply_markup=_build_markup(card.keyboard),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return str(message.message_id)
        photo = (
            BufferedInputFile(neutral_offer_cover(), filename="ugc-offer.jpg")
            if cover == NEUTRAL_COVER
            else telegram_order_photo(cover)
        )
        # A timeout can happen after Telegram has accepted the message.
        message = await self._bot.send_photo(
            chat_id=int(chat_id),
            photo=photo,
            caption=card.text,
            reply_markup=_build_markup(card.keyboard),
            parse_mode="HTML",
        )
        return str(message.message_id)

    async def edit_offer_card(
        self, chat_id: str, message_id: str, card: OfferCard
    ) -> None:
        try:
            await self._bot.edit_message_caption(
                chat_id=int(chat_id),
                message_id=int(message_id),
                caption=card.text,
                reply_markup=_build_markup(card.keyboard),
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in exc.message.lower():
                raise

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        """Edit message keyboard (or remove)."""
        try:
            await self._with_retry(
                lambda: self._bot.edit_message_reply_markup(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    reply_markup=_build_markup(keyboard),
                )
            )
        except TelegramBadRequest as exc:
            msg = (getattr(exc, "message", None) or str(exc)).lower()
            if "message is not modified" not in msg:
                raise
            # Keyboard already removed or unchanged — treat as success

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Answer a callback query.

        If the query has already expired (too old or invalid ID), the error
        is ignored so the handler can continue; the user still gets the reply.
        """
        try:
            await self._with_retry(
                lambda: self._bot.answer_callback_query(
                    callback_query_id=callback_id,
                    text=text,
                    show_alert=show_alert,
                )
            )
        except TelegramBadRequest as exc:
            msg = (getattr(exc, "message", None) or str(exc)).lower()
            if "query is too old" in msg or "query id is invalid" in msg:
                return
            raise

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
        if invoice.need_email:
            kwargs["need_email"] = True
        if invoice.send_email_to_provider:
            kwargs["send_email_to_provider"] = True
        if invoice.pay_button_text or invoice.help_button:
            rows = [
                [
                    InlineKeyboardButton(
                        text=invoice.pay_button_text or "Pay", pay=True
                    )
                ]
            ]
            if invoice.help_button is not None:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=invoice.help_button.text,
                            callback_data=invoice.help_button.callback_data,
                        )
                    ]
                )
            kwargs["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=rows)
        await self._with_retry(lambda: self._bot.send_invoice(**kwargs))


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
        return ReplyKeyboardRemove(selective=False)
    if keyboard.kind == KeyboardKind.INLINE:
        inline_rows = [
            [_inline_button(btn) for btn in row] for row in keyboard.rows
        ]
        return InlineKeyboardMarkup(inline_keyboard=inline_rows)
    if keyboard.kind == KeyboardKind.REPLY:
        reply_rows = []
        for row in keyboard.rows:
            row_buttons = []
            for btn in row:
                web_app_url = getattr(btn, "web_app_url", None)
                if web_app_url:
                    row_buttons.append(
                        KeyboardButton(
                            text=btn.text,
                            web_app=WebAppInfo(url=web_app_url),
                        )
                    )
                else:
                    row_buttons.append(
                        KeyboardButton(
                            text=btn.text,
                            request_contact=btn.request_contact,
                            request_location=getattr(
                                btn, "request_location", False
                            ),
                        )
                    )
            reply_rows.append(row_buttons)
        return ReplyKeyboardMarkup(
            keyboard=reply_rows,
            resize_keyboard=keyboard.resize,
            one_time_keyboard=keyboard.one_time,
            is_persistent=keyboard.is_persistent,
        )
    return None


def _inline_button(button: Button) -> InlineKeyboardButton:
    """Build InlineKeyboardButton from neutral Button."""
    if button.copy_text:
        return InlineKeyboardButton(
            text=button.text, copy_text=CopyTextButton(text=button.copy_text)
        )
    web_app_url = getattr(button, "web_app_url", None)
    if web_app_url:
        return InlineKeyboardButton(
            text=button.text,
            web_app=WebAppInfo(url=web_app_url),
        )
    if button.url:
        return InlineKeyboardButton(
            text=button.text, url=button.url, style=button.style
        )
    return InlineKeyboardButton(
        text=button.text,
        callback_data=button.callback_data or "",
        style=button.style,
    )


def _to_labeled_price(item: InvoiceItem):
    """Convert InvoiceItem to aiogram LabeledPrice."""
    from aiogram.types import LabeledPrice

    return LabeledPrice(label=item.label, amount=item.amount_minor)
