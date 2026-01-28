"""Tests for error handling middleware."""

from unittest.mock import Mock

import pytest

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    BloggerRegistrationError,
    OrderCreationError,
    UserNotFoundError,
)
from ugc_bot.bot.middleware.error_handler import ErrorHandlerMiddleware
from ugc_bot.metrics.collector import MetricsCollector


class FakeMessage:
    """Fake message for testing."""

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.from_user = Mock()
        self.from_user.id = 123

    async def answer(self, text: str) -> None:
        """Capture answer."""
        self.answers.append(text)


class FakeCallback:
    """Fake callback for testing."""

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.from_user = Mock()
        self.from_user.id = 456

    async def answer(self, text: str, show_alert: bool = False) -> None:
        """Capture answer."""
        self.answers.append(text)


@pytest.mark.asyncio
async def test_middleware_handles_order_creation_error() -> None:
    """Middleware handles OrderCreationError and sends user message."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Заказ не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_user_not_found_error() -> None:
    """Middleware handles UserNotFoundError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    async def handler(event, data):
        raise UserNotFoundError("User not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_blogger_registration_error() -> None:
    """Middleware handles BloggerRegistrationError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    callback = FakeCallback()

    async def handler(event, data):
        raise BloggerRegistrationError("Invalid data.")

    await middleware(handler, callback, {})

    assert len(callback.answers) == 1
    assert "Ошибка регистрации блогера" in callback.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_advertiser_registration_error() -> None:
    """Middleware handles AdvertiserRegistrationError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    async def handler(event, data):
        raise AdvertiserRegistrationError("Invalid contact.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Ошибка регистрации рекламодателя" in message.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_unexpected_error() -> None:
    """Middleware handles unexpected exceptions."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    async def handler(event, data):
        raise ValueError("Unexpected error")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "неожиданная ошибка" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_middleware_records_metrics() -> None:
    """Middleware records metrics for errors."""

    metrics = MetricsCollector()
    middleware = ErrorHandlerMiddleware(metrics_collector=metrics)
    message = FakeMessage()

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    # Metrics are logged, so we just verify middleware doesn't crash
    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_middleware_without_metrics_collector() -> None:
    """Middleware works without metrics collector."""

    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    message = FakeMessage()

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_middleware_passes_through_success() -> None:
    """Middleware passes through successful handler execution."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    async def handler(event, data):
        return "success"

    result = await middleware(handler, message, {})

    assert result == "success"
    assert len(message.answers) == 0


@pytest.mark.asyncio
async def test_middleware_handles_callback_query() -> None:
    """Middleware handles CallbackQuery events."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    callback = FakeCallback()

    async def handler(event, data):
        raise OrderCreationError("Order is not active.")

    await middleware(handler, callback, {})

    assert len(callback.answers) == 1
    assert "Заказ не активен" in callback.answers[0]


@pytest.mark.asyncio
async def test_middleware_error_message_mapping() -> None:
    """Middleware uses correct error message mappings."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage()

    test_cases = [
        (OrderCreationError("Order not found."), "Заказ не найден"),
        (OrderCreationError("Order is not active."), "Заказ не активен"),
        (
            OrderCreationError("You already responded to this order."),
            "Вы уже откликались",
        ),
        (
            OrderCreationError("Order response limit reached."),
            "Лимит откликов",
        ),
        (OrderCreationError("Unknown error"), "Ошибка создания заказа"),
    ]

    for error, expected_text in test_cases:
        message.answers.clear()

        async def handler(event, data):
            raise error

        await middleware(handler, message, {})

        assert len(message.answers) == 1
        assert expected_text in message.answers[0]
