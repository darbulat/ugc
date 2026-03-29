from unittest.mock import AsyncMock

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.max.client import MaxChatNotFoundError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class FakeStateStore:
    """Minimal in-memory StateStore for testing."""

    def __init__(self, state: str | None = None) -> None:
        self._state = state

    async def get_state(self) -> str | None:
        return self._state

    async def set_state(self, state: str | None) -> None:
        self._state = state

    async def update_data(self, **kwargs) -> None:  # type: ignore[override]
        pass

    async def get_data(self) -> dict:
        return {}

    async def clear(self) -> None:
        self._state = None


@pytest.fixture
def router():
    return MaxRouter()


@pytest.fixture
def incoming_message():
    return IncomingMessage(
        chat_id="1",
        user=IncomingUser(external_id="1", messenger_type=MessengerType.MAX),
        text="/start",
        message_id="msg_1",
    )


@pytest.fixture
def incoming_callback():
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="1",
        user=IncomingUser(external_id="1", messenger_type=MessengerType.MAX),
        data="order:123",
        message_id="msg_1",
    )


# ---------------------------------------------------------------------------
# Existing behaviour (backwards-compatibility)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_message_matching(router, incoming_message):
    called = []

    @router.message(lambda m: m.text == "/start")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_route_message_no_match(router, incoming_message):
    called = []

    @router.message(lambda m: m.text == "/help")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {})
    assert len(called) == 0


@pytest.mark.asyncio
async def test_route_callback_matching(router, incoming_callback):
    called = []

    @router.callback(lambda c: (c.data or "").startswith("order:"))
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_first_matching_handler_wins(router, incoming_message):
    called = []

    @router.message(lambda m: True)
    async def first(msg, deps):
        called.append("first")

    @router.message(lambda m: True)
    async def second(msg, deps):
        called.append("second")

    await router.route_message(incoming_message, {})
    assert called == ["first"]


@pytest.mark.asyncio
async def test_include_router(router, incoming_message):
    child = MaxRouter()
    called = []

    @child.message(lambda m: m.text == "/start")
    async def handler(msg, deps):
        called.append(msg)

    router.include(child)
    await router.route_message(incoming_message, {})
    assert len(called) == 1


# ---------------------------------------------------------------------------
# message_in_state / callback_in_state — basic routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_in_state_fires_when_state_matches(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state="registration:name")

    @router.message_in_state("registration:name")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_message_in_state_does_not_fire_when_state_differs(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state="registration:email")

    @router.message_in_state("registration:name")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 0


@pytest.mark.asyncio
async def test_message_in_state_with_predicate_both_match(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state="registration:name")

    @router.message_in_state("registration:name", lambda m: m.text == "/start")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_message_in_state_with_predicate_fails_predicate(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state="registration:name")

    @router.message_in_state("registration:name", lambda m: m.text == "/help")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 0


@pytest.mark.asyncio
async def test_callback_in_state_fires_when_state_matches(
    router, incoming_callback
):
    called = []
    store = FakeStateStore(state="order:confirm")

    @router.callback_in_state("order:confirm")
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {"state_store": store})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_callback_in_state_does_not_fire_when_state_differs(
    router, incoming_callback
):
    called = []
    store = FakeStateStore(state="order:payment")

    @router.callback_in_state("order:confirm")
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {"state_store": store})
    assert len(called) == 0


@pytest.mark.asyncio
async def test_callback_in_state_with_predicate_both_match(
    router, incoming_callback
):
    called = []
    store = FakeStateStore(state="order:confirm")

    @router.callback_in_state(
        "order:confirm", lambda c: (c.data or "").startswith("order:")
    )
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {"state_store": store})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_callback_in_state_with_predicate_fails_predicate(
    router, incoming_callback
):
    called = []
    store = FakeStateStore(state="order:confirm")

    @router.callback_in_state("order:confirm", lambda c: c.data == "cancel")
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {"state_store": store})
    assert len(called) == 0


# ---------------------------------------------------------------------------
# State handlers take priority over regular handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_message_handler_takes_priority_over_regular(router):
    called = []
    store = FakeStateStore(state="registration:name")
    text_msg = IncomingMessage(
        chat_id="1",
        user=IncomingUser(external_id="1", messenger_type=MessengerType.MAX),
        text="hello",
        message_id="msg_1",
    )

    @router.message_in_state("registration:name")
    async def state_handler(msg, deps):
        called.append("state")

    @router.message(lambda m: True)
    async def regular_handler(msg, deps):
        called.append("regular")

    await router.route_message(text_msg, {"state_store": store})
    assert called == ["state"]


@pytest.mark.asyncio
async def test_command_bypasses_state_handler(router, incoming_message):
    called = []
    store = FakeStateStore(state="registration:name")

    @router.message_in_state("registration:name")
    async def state_handler(msg, deps):
        called.append("state")

    @router.message(lambda m: m.text == "/start")
    async def cmd_handler(msg, deps):
        called.append("command")

    await router.route_message(incoming_message, {"state_store": store})
    assert called == ["command"]


@pytest.mark.asyncio
async def test_state_callback_handler_takes_priority_over_regular(
    router, incoming_callback
):
    called = []
    store = FakeStateStore(state="order:confirm")

    @router.callback_in_state("order:confirm")
    async def state_handler(cb, deps):
        called.append("state")

    @router.callback(lambda c: True)
    async def regular_handler(cb, deps):
        called.append("regular")

    await router.route_callback(incoming_callback, {"state_store": store})
    assert called == ["state"]


# ---------------------------------------------------------------------------
# Falls through to regular handlers when no state handler matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_falls_through_to_regular_when_no_state_match(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state="other:state")

    @router.message_in_state("registration:name")
    async def state_handler(msg, deps):
        called.append("state")

    @router.message(lambda m: True)
    async def regular_handler(msg, deps):
        called.append("regular")

    await router.route_message(incoming_message, {"state_store": store})
    assert called == ["regular"]


@pytest.mark.asyncio
async def test_falls_through_to_regular_when_no_state_store(
    router, incoming_message
):
    called = []

    @router.message_in_state("registration:name")
    async def state_handler(msg, deps):
        called.append("state")

    @router.message(lambda m: True)
    async def regular_handler(msg, deps):
        called.append("regular")

    # No state_store in deps — state handlers must be skipped entirely
    await router.route_message(incoming_message, {})
    assert called == ["regular"]


@pytest.mark.asyncio
async def test_falls_through_to_regular_callback_when_no_state_store(
    router, incoming_callback
):
    called = []

    @router.callback_in_state("order:confirm")
    async def state_handler(cb, deps):
        called.append("state")

    @router.callback(lambda c: True)
    async def regular_handler(cb, deps):
        called.append("regular")

    await router.route_callback(incoming_callback, {})
    assert called == ["regular"]


# ---------------------------------------------------------------------------
# Null state in store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_in_state_does_not_fire_when_store_state_is_none(
    router, incoming_message
):
    called = []
    store = FakeStateStore(state=None)

    @router.message_in_state("registration:name")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 0


# ---------------------------------------------------------------------------
# include() merges state handlers too
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_include_merges_state_message_handlers(router, incoming_message):
    child = MaxRouter()
    called = []
    store = FakeStateStore(state="registration:name")

    @child.message_in_state("registration:name")
    async def handler(msg, deps):
        called.append(msg)

    router.include(child)
    await router.route_message(incoming_message, {"state_store": store})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_include_merges_state_callback_handlers(
    router, incoming_callback
):
    child = MaxRouter()
    called = []
    store = FakeStateStore(state="order:confirm")

    @child.callback_in_state("order:confirm")
    async def handler(cb, deps):
        called.append(cb)

    router.include(child)
    await router.route_callback(incoming_callback, {"state_store": store})
    assert len(called) == 1


# ---------------------------------------------------------------------------
# Error handling in state handlers (logs, does not propagate)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_message_handler_exception_is_caught(
    router, incoming_message
):
    store = FakeStateStore(state="registration:name")

    @router.message_in_state("registration:name")
    async def bad_handler(msg, deps):
        raise RuntimeError("boom")

    # Should not raise; error is logged internally
    await router.route_message(incoming_message, {"state_store": store})


@pytest.mark.asyncio
async def test_state_callback_handler_exception_is_caught(
    router, incoming_callback
):
    store = FakeStateStore(state="order:confirm")

    @router.callback_in_state("order:confirm")
    async def bad_handler(cb, deps):
        raise RuntimeError("boom")

    await router.route_callback(incoming_callback, {"state_store": store})


# ---------------------------------------------------------------------------
# Predicate errors skip to next handler instead of stopping routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_predicate_error_skips_to_next_handler(router, incoming_message):
    called = []

    @router.message(lambda m: m.nonexistent_attr)  # type: ignore[attr-defined]
    async def bad_pred(msg, deps):
        called.append("bad")

    @router.message(lambda m: True)
    async def good(msg, deps):
        called.append("good")

    await router.route_message(incoming_message, {})
    assert called == ["good"]


@pytest.mark.asyncio
async def test_callback_predicate_error_skips_to_next(
    router, incoming_callback
):
    called = []

    @router.callback(lambda c: c.nonexistent)  # type: ignore[attr-defined]
    async def bad_pred(cb, deps):
        called.append("bad")

    @router.callback(lambda c: True)
    async def good(cb, deps):
        called.append("good")

    await router.route_callback(incoming_callback, {})
    assert called == ["good"]


# ---------------------------------------------------------------------------
# Handler errors send error message to user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_error_sends_error_message(router, incoming_message):
    mock_client = AsyncMock()

    @router.message(lambda m: True)
    async def bad(msg, deps):
        raise RuntimeError("boom")

    await router.route_message(
        incoming_message, {"messenger_client": mock_client}
    )
    mock_client.send_text.assert_called_once()
    call_kwargs = mock_client.send_text.call_args[1]
    assert call_kwargs["chat_id"] == "1"
    assert "ошибка" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_callback_handler_error_sends_error_message(
    router, incoming_callback
):
    mock_client = AsyncMock()

    @router.callback(lambda c: True)
    async def bad(cb, deps):
        raise RuntimeError("boom")

    await router.route_callback(
        incoming_callback, {"messenger_client": mock_client}
    )
    assert mock_client.send_text.call_count >= 1
    last_send = mock_client.send_text.call_args_list[-1]
    assert "ошибка" in last_send[1]["text"].lower()


@pytest.mark.asyncio
async def test_callback_handler_chat_not_found_does_not_send_error_message(
    router, incoming_callback
):
    mock_client = AsyncMock()

    @router.callback(lambda c: True)
    async def chat_missing(cb, deps):
        raise MaxChatNotFoundError(
            '{"code":"chat.not.found","message":"Chat missing"}'
        )

    await router.route_callback(
        incoming_callback, {"messenger_client": mock_client}
    )
    mock_client.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_handler_error_with_failing_send_error_is_swallowed(
    router, incoming_message
):
    mock_client = AsyncMock()
    mock_client.send_text.side_effect = RuntimeError("send failed")

    @router.message(lambda m: True)
    async def bad(msg, deps):
        raise RuntimeError("boom")

    await router.route_message(
        incoming_message, {"messenger_client": mock_client}
    )


@pytest.mark.asyncio
async def test_callback_predicate_false_then_true_handler_runs(
    router, incoming_callback
):
    called = []

    @router.callback(lambda c: False)
    async def never_called(cb, deps):
        called.append("never")

    @router.callback(lambda c: True)
    async def called_handler(cb, deps):
        called.append("called")

    await router.route_callback(incoming_callback, {})
    assert called == ["called"]


@pytest.mark.asyncio
async def test_callback_keyboard_removal_failure_does_not_break_routing(
    router, incoming_callback
):
    mock_client = AsyncMock()
    mock_client.edit_reply_markup.side_effect = RuntimeError("edit failed")
    called = []

    @router.callback(lambda c: True)
    async def good(cb, deps):
        called.append("ok")

    await router.route_callback(
        incoming_callback, {"messenger_client": mock_client}
    )
    assert called == ["ok"]
