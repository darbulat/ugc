"""Error handling middleware for aiogram handlers.

This middleware centralizes error handling for application errors,
providing consistent logging, metrics, and user-facing messages.

When using JSON log format in production, ensure that the data passed
in ``extra`` (and thus in log output) never contains sensitive data
such as tokens, passwords, or full message payloads.
"""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

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
        "You already responded to this order.": "Вы уже откликались на этот заказ.",
        "Order response limit reached.": "Лимит откликов по заказу достигнут.",
        "Order is not in NEW status.": "Заказ не в статусе NEW.",
        "Order does not belong to advertiser.": "Заказ не принадлежит рекламодателю.",
        "default": "Ошибка создания заказа.",
    },
    InteractionNotFoundError: {
        "default": "Взаимодействие не найдено.",
    },
    InteractionError: {
        "Interaction not found.": "Взаимодействие не найдено.",
        "Interaction is not in ISSUE status.": "Взаимодействие не в статусе ISSUE.",
        "Final status must be OK or NO_DEAL for manual resolution.": "Некорректный статус для ручного разрешения.",
        "default": "Ошибка взаимодействия.",
    },
    ComplaintAlreadyExistsError: {
        "Вы уже подали жалобу по этому заказу.": "Вы уже подали жалобу по этому заказу.",
        "default": "Вы уже подали жалобу по этому заказу.",
    },
    ComplaintNotFoundError: {
        "Complaint not found.": "Жалоба не найдена.",
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

    return f"Произошла ошибка: {error_str}"


def _get_user_id(event: TelegramObject) -> str | None:
    """Extract user ID from event."""
    if isinstance(event, Message) and event.from_user:
        return str(event.from_user.id)
    if isinstance(event, CallbackQuery) and event.from_user:
        return str(event.from_user.id)
    return None


async def _send_error_message(event: TelegramObject, message: str) -> None:
    """Send error message to user."""
    if isinstance(event, Message):
        await event.answer(message)
    elif isinstance(event, CallbackQuery):
        await event.answer(message, show_alert=False)
    elif hasattr(event, "answer"):
        # Support test fixtures and other objects with answer method
        answer_method = getattr(event, "answer")
        if callable(answer_method):
            # Try with show_alert=False for callback-like objects, fallback to no args
            try:
                await answer_method(message, show_alert=False)
            except TypeError:
                await answer_method(message)


class ErrorHandlerMiddleware(BaseMiddleware):
    """Middleware for handling application errors consistently."""

    def __init__(self, metrics_collector: MetricsCollector | None = None) -> None:
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

            if self.metrics_collector:
                if hasattr(self.metrics_collector, "record_error"):
                    self.metrics_collector.record_error(
                        error_type=error_type,
                        error_message=error_message,
                        user_id=user_id or "unknown",
                    )

            user_message = _get_user_message(exc)
            await _send_error_message(event, user_message)
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

            if self.metrics_collector:
                if hasattr(self.metrics_collector, "record_error"):
                    self.metrics_collector.record_error(
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        user_id=user_id or "unknown",
                    )

            await _send_error_message(
                event, "Произошла неожиданная ошибка. Попробуйте позже."
            )
            return None
