"""Error handling middleware for aiogram handlers.

This middleware centralizes error handling for application errors,
providing consistent logging, metrics, and user-facing messages.

When using JSON log format in production, ensure that the data passed
in ``extra`` (and thus in log output) never contains sensitive data
such as tokens, passwords, or full message payloads.
"""

import logging
from typing import Any, Awaitable, Callable, cast

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    Message,
    PreCheckoutQuery,
    TelegramObject,
)

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    BloggerRegistrationError,
    ComplaintAlreadyExistsError,
    ComplaintNotFoundError,
    InteractionError,
    InteractionNotFoundError,
    OrderCreationError,
    UserNotFoundError,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
    PaymentProvider,
)
from ugc_bot.application.services.order_service import MAX_ORDER_PRICE
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


# Error message mappings for user-facing messages
ERROR_MESSAGES = {
    UserNotFoundError: {
        "default": "Пользователь не найден.",
    },
    BloggerRegistrationError: {
        "default": "Ошибка регистрации блогера.",
    },
    AdvertiserRegistrationError: {
        "default": "Ошибка регистрации рекламодателя.",
    },
    OrderCreationError: {
        "Order not found.": "Заказ не найден.",
        "Order is not active.": "Заказ не активен.",
        "You already responded to this order.": "Вы уже откликались на заказ.",
        "Order response limit reached.": "Лимит откликов по заказу достигнут.",
        "Order is not in NEW status.": "Заказ не в статусе NEW.",
        "Order does not belong to advertiser.": (
            "Заказ не принадлежит рекламодателю."
        ),
        f"Price exceeds maximum ({MAX_ORDER_PRICE:,.0f}).": (
            f"Сумма превышает максимум ({MAX_ORDER_PRICE:,.0f} ₽)."
        ),
        "default": "Ошибка создания заказа.",
    },
    InteractionNotFoundError: {
        "default": "Взаимодействие не найдено.",
    },
    InteractionError: {
        "Interaction not found.": "Взаимодействие не найдено.",
        "Interaction is not in ISSUE status.": "Взаимодействие не в ISSUE.",
        "Final status must be OK or NO_DEAL for manual resolution.": (
            "Некорректный статус для ручного разрешения."
        ),
        "default": "Ошибка взаимодействия.",
    },
    ComplaintAlreadyExistsError: {
        "Вы уже подали жалобу по этому заказу.": (
            "Вы уже подали жалобу по этому заказу."
        ),
        "default": "Вы уже подали жалобу по этому заказу.",
    },
    ComplaintNotFoundError: {
        "Complaint not found.": ("Жалоба не найдена."),
        "default": "Жалоба не найдена.",
    },
}


def _get_user_message(error: Exception) -> str:
    """Get user-friendly message for an error."""
    error_type = type(error)
    error_str = str(error)

    if error_type in ERROR_MESSAGES:
        messages = ERROR_MESSAGES[error_type]
        if error_str in messages:
            return messages[error_str]
        if "default" in messages:
            return messages["default"]

    return f"Произошла ошибка: {error_str}"  # pragma: no cover


def _get_user_id(event: TelegramObject) -> str | None:
    """Extract user ID from event."""
    if isinstance(event, Message) and event.from_user:
        return str(event.from_user.id)
    if isinstance(event, CallbackQuery) and event.from_user:
        return str(event.from_user.id)
    if isinstance(event, PreCheckoutQuery) and event.from_user:
        return str(event.from_user.id)
    return None  # pragma: no cover - defensive fallback for test fixtures


async def _send_via_messenger_client(
    event: TelegramObject,
    message: str,
    messenger_client: MessengerClient,
    event_adapter: MessengerEventAdapter,
    payment_provider: PaymentProvider | None,
) -> bool:
    """Send error via MessengerClient. Return True if sent."""
    try:
        if isinstance(event, Message):
            incoming_msg = event_adapter.from_message(event)
            await messenger_client.send_text(
                chat_id=incoming_msg.chat_id, text=message
            )
            return True
        if isinstance(event, CallbackQuery):
            incoming_cb = event_adapter.from_callback(event)
            await messenger_client.answer_callback(
                callback_id=incoming_cb.callback_id,
                text=message,
                show_alert=False,
            )
            return True
        if isinstance(event, PreCheckoutQuery) and payment_provider:
            await payment_provider.reject_pre_checkout(
                query_id=event.id, error_message=message[:255]
            )
            return True
    except Exception:
        pass
    return False


async def _send_error_message(
    event: TelegramObject,
    message: str,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    payment_provider: PaymentProvider | None = None,
) -> None:
    """Send error message to user via MessengerClient or event.answer."""
    if messenger_client and event_adapter:
        sent = await _send_via_messenger_client(
            event, message, messenger_client, event_adapter, payment_provider
        )
        if sent:
            return
    if isinstance(event, Message):
        await event.answer(message)
    elif isinstance(event, CallbackQuery):
        await event.answer(message, show_alert=False)
    elif hasattr(event, "answer"):
        answer_method = event.answer
        if callable(answer_method):
            try:
                await answer_method(message, show_alert=False)
            except TypeError:  # pragma: no cover
                await answer_method(message)


class ErrorHandlerMiddleware(BaseMiddleware):
    """Middleware for handling application errors consistently."""

    def __init__(
        self, metrics_collector: MetricsCollector | None = None
    ) -> None:
        """Initialize error handler middleware.

        Args:
            metrics_collector: Optional metrics collector for recording errors.
        """
        self.metrics_collector = metrics_collector

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Process handler and catch application errors."""
        messenger_client = data.get("messenger_client")
        event_adapter = data.get("event_adapter")
        payment_provider = data.get("payment_provider")
        resolved_adapter = cast(
            MessengerEventAdapter,
            event_adapter
            if event_adapter is not None
            else TelegramEventAdapter(),
        )
        try:
            return await handler(event, data)
        except (
            UserNotFoundError,
            BloggerRegistrationError,
            AdvertiserRegistrationError,
            OrderCreationError,
            InteractionNotFoundError,
            InteractionError,
            ComplaintAlreadyExistsError,
            ComplaintNotFoundError,
        ) as exc:
            # Application error - log, record metric, send user message
            user_id = _get_user_id(event)
            error_type = type(exc).__name__
            error_message = str(exc)

            logger.warning(
                "Application error in handler",
                extra={
                    "error_type": error_type,
                    "error_message": error_message,
                    "user_id": user_id,
                    "event_type": type(event).__name__,
                },
            )

            if self.metrics_collector and hasattr(
                self.metrics_collector, "record_error"
            ):
                self.metrics_collector.record_error(
                    error_type=error_type,
                    error_message=error_message,
                    user_id=user_id or "unknown",
                )

            user_message = _get_user_message(exc)
            await _send_error_message(
                event,
                user_message,
                messenger_client,
                resolved_adapter,
                payment_provider,
            )
            return None

        except Exception as exc:
            # Unexpected error - log exception, send generic message
            user_id = _get_user_id(event)

            logger.exception(
                "Unexpected error in handler",
                extra={
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "user_id": user_id,
                    "event_type": type(event).__name__,
                },
            )

            if self.metrics_collector and hasattr(
                self.metrics_collector, "record_error"
            ):
                self.metrics_collector.record_error(
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    user_id=user_id or "unknown",
                )

            await _send_error_message(
                event,
                "Произошла неожиданная ошибка. Попробуйте позже.",
                messenger_client,
                resolved_adapter,
                payment_provider,
            )
            return None
