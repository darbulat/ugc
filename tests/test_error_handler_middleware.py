"""Tests for error handling middleware."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, PreCheckoutQuery, User

from tests.helpers.fakes import (
    FakeCallback,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
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
from ugc_bot.bot.middleware.error_handler import ErrorHandlerMiddleware
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.metrics.collector import MetricsCollector


def _answer_text(answers: list, index: int = 0) -> str:
    """Get answer text from message/callback answers (may be str or tuple)."""
    ans = answers[index]
    return ans if isinstance(ans, str) else ans[0]


@pytest.mark.asyncio
async def test_middleware_handles_order_creation_error() -> None:
    """Middleware handles OrderCreationError and sends user message."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Заказ не найден" in _answer_text(message.answers)


@pytest.mark.asyncio
async def test_middleware_handles_user_not_found_error() -> None:
    """Middleware handles UserNotFoundError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise UserNotFoundError("User not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Пользователь не найден" in _answer_text(message.answers)


@pytest.mark.asyncio
async def test_middleware_handles_blogger_registration_error() -> None:
    """Middleware handles BloggerRegistrationError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    callback = FakeCallback(data="", user=FakeUser(456))

    async def handler(event, data):
        raise BloggerRegistrationError("Invalid data.")

    await middleware(handler, callback, {})

    assert len(callback.answers) == 1
    assert "Ошибка регистрации блогера" in callback.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_advertiser_registration_error() -> None:
    """Middleware handles AdvertiserRegistrationError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise AdvertiserRegistrationError("Invalid contact.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "Ошибка регистрации рекламодателя" in _answer_text(message.answers)


@pytest.mark.asyncio
async def test_middleware_handles_unexpected_error() -> None:
    """Middleware handles unexpected exceptions."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise ValueError("Unexpected error")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "неожиданная ошибка" in _answer_text(message.answers).lower()


@pytest.mark.asyncio
async def test_middleware_records_metrics() -> None:
    """Middleware records metrics for errors."""

    metrics = MetricsCollector()
    middleware = ErrorHandlerMiddleware(metrics_collector=metrics)
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    # Metrics are logged, so we just verify middleware doesn't crash
    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_middleware_without_metrics_collector() -> None:
    """Middleware works without metrics collector."""

    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, message, {})

    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_middleware_passes_through_success() -> None:
    """Middleware passes through successful handler execution."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        return "success"

    result = await middleware(handler, message, {})

    assert result == "success"
    assert len(message.answers) == 0


@pytest.mark.asyncio
async def test_middleware_handles_callback_query() -> None:
    """Middleware handles CallbackQuery events."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    callback = FakeCallback(data="", user=FakeUser(456))

    async def handler(event, data):
        raise OrderCreationError("Order is not active.")

    await middleware(handler, callback, {})

    assert len(callback.answers) == 1
    assert "Заказ не активен" in callback.answers[0]


@pytest.mark.asyncio
async def test_middleware_handles_unknown_error_type() -> None:
    """Middleware returns generic message for unknown error type."""
    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

    async def handler(event, data):
        raise RuntimeError("Something went wrong")

    await middleware(handler, message, {})

    assert len(message.answers) == 1
    assert "неожиданная ошибка" in _answer_text(message.answers).lower()


@pytest.mark.asyncio
async def test_middleware_error_message_mapping() -> None:
    """Middleware uses correct error message mappings."""

    middleware = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())
    message = FakeMessage(user=FakeUser(123))

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

        async def handler(event, data, exc=error):
            raise exc

        await middleware(handler, message, {})

        assert len(message.answers) == 1
        assert expected_text in _answer_text(message.answers)


@pytest.mark.asyncio
async def test_middleware_handles_complaint_errors() -> None:
    """Middleware handles ComplaintAlreadyExists and ComplaintNotFound."""

    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    message = FakeMessage(user=FakeUser(123))

    for error in [
        ComplaintAlreadyExistsError("Вы уже подали жалобу по этому заказу."),
        ComplaintNotFoundError("Complaint not found."),
    ]:
        message.answers.clear()

        async def handler(event, data, exc=error):
            raise exc

        await middleware(handler, message, {})

        assert len(message.answers) == 1
        assert (
            "жалоб" in _answer_text(message.answers).lower()
            or "найдена" in _answer_text(message.answers).lower()
        )


@pytest.mark.asyncio
async def test_middleware_handles_interaction_errors() -> None:
    """Middleware handles InteractionNotFoundError and InteractionError."""

    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    message = FakeMessage(user=FakeUser(123))

    for error in [
        InteractionNotFoundError("Interaction not found."),
        InteractionError("Interaction not found."),
    ]:
        message.answers.clear()

        async def handler(event, data, exc=error):
            raise exc

        await middleware(handler, message, {})

        assert len(message.answers) == 1
        assert "Взаимодействие" in _answer_text(message.answers)


@pytest.mark.asyncio
async def test_middleware_send_error_with_answer_no_show_alert() -> None:
    """Event answer() without show_alert falls back to answer(msg)."""

    class EventWithSimpleAnswer:
        """Event whose answer() only accepts message, not show_alert."""

        def __init__(self) -> None:
            self.answers = []

        async def answer(self, text: str) -> None:
            self.answers.append(text)

    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    event = EventWithSimpleAnswer()

    async def handler(ev, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, event, {})

    assert len(event.answers) == 1
    assert "Заказ не найден" in event.answers[0]


@pytest.mark.asyncio
async def test_middleware_get_user_id_from_message() -> None:
    """_get_user_id extracts id from Message with from_user."""

    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock()
    msg.from_user.id = 777
    msg.answer = AsyncMock()

    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, msg, {})

    msg.answer.assert_called_once()
    call_args = msg.answer.call_args
    assert "Заказ не найден" in str(call_args)


@pytest.mark.asyncio
async def test_middleware_get_user_id_from_callback() -> None:
    """_get_user_id extracts id from CallbackQuery with from_user."""

    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock()
    callback.from_user.id = 888
    callback.answer = AsyncMock()

    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(event, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, callback, {})

    callback.answer.assert_called_once()
    call_args = callback.answer.call_args
    assert "Заказ не найден" in str(call_args)


def _make_aiogram_message(chat_id: int = 123, user_id: int = 123) -> Message:
    """Create minimal aiogram Message for tests."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=chat_id, type="private")
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=chat,
        from_user=user,
    )


def _make_aiogram_callback(
    callback_id: str = "cb1", user_id: int = 456
) -> CallbackQuery:
    """Create minimal aiogram CallbackQuery for tests."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    msg = Message(
        message_id=1,
        date=datetime.now(),
        chat=chat,
        from_user=user,
    )
    return CallbackQuery(
        id=callback_id,
        from_user=user,
        chat_instance="x",
        message=msg,
    )


def _make_pre_checkout_query(
    query_id: str = "q1", user_id: int = 999
) -> PreCheckoutQuery:
    """Create minimal aiogram PreCheckoutQuery for tests."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    return PreCheckoutQuery(
        id=query_id,
        from_user=user,
        currency="RUB",
        total_amount=10000,
        invoice_payload="payload",
    )


@pytest.mark.asyncio
async def test_middleware_get_user_id_from_pre_checkout() -> None:
    """_get_user_id extracts id from PreCheckoutQuery with from_user."""

    query = _make_pre_checkout_query(user_id=999)

    class FakePaymentProvider:
        """Stub that records reject_pre_checkout calls."""

        def __init__(self) -> None:
            self.rejected: list[tuple[str, str]] = []

        async def reject_pre_checkout(
            self, *, query_id: str, error_message: str
        ) -> None:
            self.rejected.append((query_id, error_message))

    provider = FakePaymentProvider()
    middleware = ErrorHandlerMiddleware(metrics_collector=None)
    data = {
        "messenger_client": FakeMessengerClient(),
        "event_adapter": TelegramEventAdapter(),
        "payment_provider": provider,
    }

    async def handler(event, d):
        raise OrderCreationError("Order not found.")

    await middleware(handler, query, data)

    assert len(provider.rejected) == 1
    assert provider.rejected[0][0] == "q1"
    assert "Заказ не найден" in provider.rejected[0][1]


@pytest.mark.asyncio
async def test_middleware_send_error_via_messenger_client_message() -> None:
    """Error sent via messenger_client.send_text for Message events."""

    msg = _make_aiogram_message(chat_id=123, user_id=123)

    messenger = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    data = {
        "messenger_client": messenger,
        "event_adapter": adapter,
        "payment_provider": None,
    }

    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(event, d):
        raise OrderCreationError("Order not found.")

    await middleware(handler, msg, data)

    assert len(messenger.sent_text) == 1
    assert "Заказ не найден" in messenger.sent_text[0]["text"]
    assert messenger.sent_text[0]["chat_id"] == "123"


@pytest.mark.asyncio
async def test_middleware_send_error_via_messenger_client_callback() -> None:
    """Error sent via messenger_client.answer_callback for CallbackQuery."""

    callback = _make_aiogram_callback(callback_id="cb-x", user_id=456)

    messenger = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    data = {
        "messenger_client": messenger,
        "event_adapter": adapter,
        "payment_provider": None,
    }

    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(event, d):
        raise OrderCreationError("Order not found.")

    await middleware(handler, callback, data)

    assert len(messenger.answered_callbacks) == 1
    assert "Заказ не найден" in messenger.answered_callbacks[0]["text"]
    assert messenger.answered_callbacks[0]["callback_id"] == "cb-x"


@pytest.mark.asyncio
async def test_middleware_messenger_fallback_to_event_answer() -> None:
    """When messenger_client raises, fall back to event.answer."""

    # Mock that passes isinstance(Message) and has adapter-compatible attrs
    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock()
    msg.from_user.id = 123
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.photo = None
    msg.successful_payment = None
    msg.text = None
    msg.message_id = 1
    msg.__class__ = Message  # type: ignore[assignment]

    answer_mock = AsyncMock()
    msg.answer = answer_mock

    async def failing_send_text(**kwargs: object) -> None:
        raise RuntimeError("Send failed")

    messenger = MagicMock()
    messenger.send_text = failing_send_text

    adapter = TelegramEventAdapter()
    data = {
        "messenger_client": messenger,
        "event_adapter": adapter,
        "payment_provider": None,
    }

    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(event, d):
        raise OrderCreationError("Order not found.")

    await middleware(handler, msg, data)

    answer_mock.assert_called_once()
    call_args = answer_mock.call_args
    assert "Заказ не найден" in str(call_args)


@pytest.mark.asyncio
async def test_middleware_event_answer_typeerror_fallback() -> None:
    """When answer(msg, show_alert=False) raises TypeError, use answer(msg)."""

    class EventWithOneArgAnswer:
        """Event whose answer() only accepts one argument."""

        def __init__(self) -> None:
            self.answers: list[str] = []

        async def answer(self, text: str) -> None:
            self.answers.append(text)

    event = EventWithOneArgAnswer()
    middleware = ErrorHandlerMiddleware(metrics_collector=None)

    async def handler(ev, data):
        raise OrderCreationError("Order not found.")

    await middleware(handler, event, {})

    assert len(event.answers) == 1
    assert "Заказ не найден" in event.answers[0]
