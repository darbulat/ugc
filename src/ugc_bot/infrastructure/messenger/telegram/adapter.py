"""Telegram event adapter."""

from typing import Any

from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingPreCheckout,
    IncomingUser,
    PaymentSuccess,
)
from ugc_bot.domain.enums import MessengerType


class TelegramEventAdapter:
    """Convert Telegram events into neutral DTOs."""

    def from_message(self, message: Message) -> IncomingMessage:
        """Convert aiogram Message into IncomingMessage."""
        user = message.from_user
        external_id = str(user.id) if user else ""
        username = user.username if user else None
        chat_id = str(message.chat.id) if message.chat else ""
        photo_file_ids = [photo.file_id for photo in (message.photo or [])]
        successful_payment = None
        if message.successful_payment:
            successful_payment = PaymentSuccess(
                invoice_payload=message.successful_payment.invoice_payload,
                provider_payment_charge_id=(
                    message.successful_payment.provider_payment_charge_id
                ),
                total_amount=message.successful_payment.total_amount,
                currency=message.successful_payment.currency,
            )
        return IncomingMessage(
            chat_id=chat_id,
            user=IncomingUser(
                external_id=external_id,
                messenger_type=MessengerType.TELEGRAM,
                username=username,
            ),
            text=message.text,
            message_id=str(message.message_id),
            photo_file_ids=photo_file_ids,
            successful_payment=successful_payment,
            raw=_safe_raw(message),
        )

    def from_callback(self, callback: CallbackQuery) -> IncomingCallback:
        """Convert aiogram CallbackQuery into IncomingCallback."""
        user = callback.from_user
        external_id = str(user.id) if user else ""
        username = user.username if user else None
        message = callback.message
        chat_id = str(message.chat.id) if message else ""
        message_id = str(message.message_id) if message else None
        return IncomingCallback(
            callback_id=callback.id,
            chat_id=chat_id,
            user=IncomingUser(
                external_id=external_id,
                messenger_type=MessengerType.TELEGRAM,
                username=username,
            ),
            data=callback.data,
            message_id=message_id,
            raw=_safe_raw(callback),
        )

    def from_pre_checkout(self, query: PreCheckoutQuery) -> IncomingPreCheckout:
        """Convert aiogram PreCheckoutQuery into IncomingPreCheckout."""
        user = query.from_user
        external_id = str(user.id) if user else ""
        username = user.username if user else None
        return IncomingPreCheckout(
            query_id=query.id,
            user=IncomingUser(
                external_id=external_id,
                messenger_type=MessengerType.TELEGRAM,
                username=username,
            ),
            payload=query.invoice_payload,
        )


def _safe_raw(obj: Any) -> dict[str, Any] | None:
    """Best-effort conversion to dict for logging/debug."""
    try:
        return obj.model_dump()
    except Exception:
        return None
