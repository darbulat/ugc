"""Tests for handler utilities."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.handlers.keyboards import (
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
    draft_choice_keyboard,
)
from ugc_bot.bot.handlers.utils import (
    LegacyMessengerClient,
    RateLimiter,
    _answer_callback_or_fallback,
    _normalize_draft_choice_args,
    _resolve_user_lookup_from_callback,
    _resolve_user_lookup_from_message,
    _send_draft_text,
    _send_text_or_answer,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    handle_draft_choice,
    parse_user_id_from_state,
    send_with_retry,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus


def test_rate_limiter_allows_within_limit() -> None:
    """Allow requests within the limit."""

    limiter = RateLimiter(limit=2, window_seconds=10.0)
    assert limiter.allow("key") is True
    assert limiter.allow("key") is True
    assert limiter.allow("key") is False


@pytest.mark.asyncio
async def test_send_with_retry_success() -> None:
    """Return True on successful send."""

    messenger_client = FakeMessengerClient()
    ok = await send_with_retry(
        messenger_client,
        chat_id="1",
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is True
    assert len(messenger_client.sent_text) == 1


@pytest.mark.asyncio
async def test_send_with_retry_failure() -> None:
    """Return False after retries exhausted."""

    class FailingMessenger:
        async def send_text(self, *, chat_id: str, text: str, **kwargs) -> None:
            raise RuntimeError("fail")

    ok = await send_with_retry(
        FailingMessenger(),
        chat_id="1",
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False


def test_parse_user_id_from_state_missing() -> None:
    """Return None when key is missing."""
    assert parse_user_id_from_state({}, key="user_id") is None
    assert parse_user_id_from_state({"other": "x"}, key="user_id") is None


def test_parse_user_id_from_state_from_string() -> None:
    """Parse UUID from string value."""
    uid = uuid4()
    assert parse_user_id_from_state({"user_id": str(uid)}) == uid


def test_parse_user_id_from_state_already_uuid() -> None:
    """Return UUID when value is already UUID."""
    uid = uuid4()
    assert parse_user_id_from_state({"user_id": uid}) == uid


def test_parse_user_id_from_state_custom_key() -> None:
    """Use custom key (e.g. edit_user_id)."""
    uid = uuid4()
    assert (
        parse_user_id_from_state({"edit_user_id": str(uid)}, key="edit_user_id")
        == uid
    )


def test_parse_user_id_from_state_invalid_string() -> None:
    """Return None for invalid UUID string."""
    assert parse_user_id_from_state({"user_id": "not-a-uuid"}) is None


def test_parse_user_id_from_state_invalid_type() -> None:
    """Return None when value is not str or UUID (e.g. int, list)."""
    assert parse_user_id_from_state({"user_id": 123}) is None
    assert parse_user_id_from_state({"user_id": []}) is None


def test_resolve_user_lookup_from_message_fallback() -> None:
    """Fallback uses from_user and answer when message is not DTO."""

    class DummyMessage:
        def __init__(self) -> None:
            self.from_user = type("U", (), {"id": 42})()

        async def answer(self, text: str, **kwargs) -> None:
            _ = text, kwargs

    dummy = DummyMessage()
    (
        external_id,
        messenger_type,
        chat_id,
        answer,
        client,
        service,
    ) = _resolve_user_lookup_from_message(dummy, "svc", None)
    assert external_id == "42"
    assert chat_id == "42"
    assert messenger_type == MessengerType.TELEGRAM
    assert callable(answer)
    assert client is None
    assert service == "svc"


def test_resolve_user_lookup_from_callback_fallback() -> None:
    """Fallback uses from_user and answer when callback is not DTO."""

    class DummyCallback:
        def __init__(self) -> None:
            self.from_user = type("U", (), {"id": 7})()

        async def answer(self, text: str, **kwargs) -> None:
            _ = text, kwargs

    dummy = DummyCallback()
    (
        external_id,
        messenger_type,
        callback_id,
        answer,
        client,
        service,
    ) = _resolve_user_lookup_from_callback(dummy, "svc", None)
    assert external_id == "7"
    assert callback_id == ""
    assert messenger_type == MessengerType.TELEGRAM
    assert callable(answer)
    assert client is None
    assert service == "svc"


@pytest.mark.asyncio
async def test_send_text_or_answer_fallback_text_only() -> None:
    """Fallback sends text via answer when client missing."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _send_text_or_answer(
        None,
        chat_id="1",
        text="hello",
        answer=answer,
        keyboard=None,
    )
    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_send_draft_text_fallback_text_only() -> None:
    """Draft text fallback uses message.answer for text-only send."""
    calls: list[str] = []

    class DummyMessage:
        chat_id = "1"

        async def answer(self, text: str) -> None:
            calls.append(text)

    await _send_draft_text(
        None,
        DummyMessage(),
        text="draft",
        keyboard=None,
    )
    assert calls == ["draft"]


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_none() -> None:
    """When user is None, send user_not_found_msg and return None."""

    class NoUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> None:
            return None

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        NoUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert messenger_client.sent_text[0]["text"] == "Not found"


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_blocked() -> None:
    """When user is BLOCKED, send blocked_msg and return None."""

    blocked_user = User(
        user_id=uuid4(),
        external_id="456",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class BlockedUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return blocked_user

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="456",
        user=IncomingUser(
            external_id="456",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        BlockedUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert messenger_client.sent_text[0]["text"] == "Blocked"


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_ok() -> None:
    """When user is allowed, return user."""

    ok_user = User(
        user_id=uuid4(),
        external_id="789",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class OkUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return ok_user

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="789",
        user=IncomingUser(
            external_id="789",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        OkUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is ok_user
    assert result is not None


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_callback_ok() -> None:
    """Callback variant returns user when allowed."""

    ok_user = User(
        user_id=uuid4(),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class OkUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return ok_user

    messenger_client = FakeMessengerClient()
    callback = IncomingCallback(
        callback_id="cb-1",
        chat_id="999",
        user=IncomingUser(
            external_id="999",
            messenger_type=MessengerType.TELEGRAM,
        ),
        data="x",
        message_id="1",
    )
    result = await get_user_and_ensure_allowed_callback(
        callback,
        messenger_client,
        OkUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is ok_user
    assert messenger_client.answered_callbacks == []


def test_normalize_draft_choice_args_shifts_when_no_client() -> None:
    """Shift args when called without messenger client."""

    class DummyState:
        async def get_data(self) -> dict:
            return {}

    dummy_state = DummyState()
    dummy_service = object()
    client, state, service = _normalize_draft_choice_args(
        dummy_state, dummy_service, None
    )
    assert client is None
    assert state is dummy_state
    assert service is dummy_service


@pytest.mark.asyncio
async def test_send_text_or_answer_handles_type_error() -> None:
    """Fallback to answer(text) when keyboard arg is unsupported."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _send_text_or_answer(
        None,
        chat_id="1",
        text="hello",
        answer=answer,
        keyboard=draft_choice_keyboard(),
    )
    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_send_draft_text_handles_type_error() -> None:
    """Fallback to answer(text) when keyboard arg is unsupported."""
    calls: list[str] = []

    class DummyMessage:
        chat_id = "1"

        async def answer(self, text: str) -> None:
            calls.append(text)

    await _send_draft_text(
        None,
        DummyMessage(),
        text="draft",
        keyboard=draft_choice_keyboard(),
    )
    assert calls == ["draft"]


@pytest.mark.asyncio
async def test_send_with_retry_uses_send_message() -> None:
    """send_with_retry falls back to send_message."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, object]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, text, kwargs.get("reply_markup")))

    bot = DummyBot()
    ok = await send_with_retry(
        bot,
        chat_id="1",
        text="hi",
        retries=1,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
        keyboard=draft_choice_keyboard(),
    )
    assert ok is True
    assert bot.calls


@pytest.mark.asyncio
async def test_send_with_retry_invalid_client_returns_false() -> None:
    """send_with_retry returns False when no send methods."""
    ok = await send_with_retry(
        object(),
        chat_id="1",
        text="hi",
        retries=1,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False


@pytest.mark.asyncio
async def test_answer_callback_or_fallback_uses_answer() -> None:
    """Fallback to callback.answer when no messenger client."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _answer_callback_or_fallback(
        None, callback_id="", text="ok", answer=answer
    )
    assert calls == ["ok"]


def test_normalize_draft_choice_args_requires_service() -> None:
    """Raise when draft service is missing and no state provided."""
    with pytest.raises(ValueError):
        _normalize_draft_choice_args(object(), object(), None)


@pytest.mark.asyncio
async def test_legacy_messenger_client_uses_bot_send_message() -> None:
    """LegacyMessengerClient sends via bot when no answer."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, text))

    class DummyEvent:
        def __init__(self) -> None:
            self.bot = DummyBot()

    event = DummyEvent()
    client = LegacyMessengerClient(event)
    await client.send_text(chat_id="1", text="hello")
    assert event.bot.calls == [(1, "hello")]


@pytest.mark.asyncio
async def test_legacy_messenger_client_send_photo_via_bot() -> None:
    """LegacyMessengerClient sends photo via bot."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        async def send_photo(self, chat_id: int, photo: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, photo))

    class DummyEvent:
        def __init__(self) -> None:
            self.bot = DummyBot()

    event = DummyEvent()
    client = LegacyMessengerClient(event)
    await client.send_photo(chat_id="2", file_id="file")
    assert event.bot.calls == [(2, "file")]


@pytest.mark.asyncio
async def test_legacy_messenger_client_edit_text_uses_event() -> None:
    """LegacyMessengerClient edits text via event method."""
    calls: list[str] = []

    class DummyEvent:
        async def edit_text(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append(text)

    client = LegacyMessengerClient(DummyEvent())
    await client.edit_text(chat_id="1", message_id="1", text="edit")
    assert calls == ["edit"]


@pytest.mark.asyncio
async def test_legacy_messenger_client_edit_markup_uses_event() -> None:
    """LegacyMessengerClient edits reply markup via event method."""
    calls: list[object] = []

    class DummyEvent:
        async def edit_reply_markup(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append(kwargs.get("reply_markup"))

    client = LegacyMessengerClient(DummyEvent())
    await client.edit_reply_markup(chat_id="1", message_id="1", keyboard=None)
    assert calls == [None]


@pytest.mark.asyncio
async def test_handle_draft_choice_session_expired() -> None:
    """When user_id missing from state, clear and send session_expired_msg."""

    class FakeState:
        async def get_data(self) -> dict:
            return {}

        async def clear(self) -> None:
            self.cleared = True

        async def set_state(self, state) -> None:
            pass

        async def update_data(self, **kwargs) -> None:
            pass

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="1",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="",
    )
    state = FakeState()
    state.cleared = False

    async def get_draft(*args):  # type: ignore[no-untyped-def]
        return None

    async def delete_draft(*args):  # type: ignore[no-untyped-def]
        pass

    draft_service = type(
        "S", (), {"get_draft": get_draft, "delete_draft": delete_draft}
    )()

    await handle_draft_choice(
        message,
        messenger_client,
        state,
        draft_service,
        flow_type="test",
        user_id_key="user_id",
        first_state="FirstState",
        first_prompt="Start",
        first_keyboard=draft_choice_keyboard(),
        session_expired_msg="Session expired",
    )
    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == "Session expired"


@pytest.mark.asyncio
async def test_handle_draft_choice_resume_draft_none() -> None:
    """When RESUME_DRAFT but draft None, show draft_used_msg and first step."""

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            self.state = state

        async def update_data(self, **kwargs) -> None:
            pass

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="1",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text=RESUME_DRAFT_BUTTON_TEXT,
    )
    state = FakeState()

    async def get_draft(*args):  # type: ignore[no-untyped-def]
        return None

    async def delete_draft(*args):  # type: ignore[no-untyped-def]
        pass

    draft_service = type(
        "S", (), {"get_draft": get_draft, "delete_draft": delete_draft}
    )()

    await handle_draft_choice(
        message,
        messenger_client,
        state,
        draft_service,
        flow_type="test",
        user_id_key="user_id",
        first_state="FirstState",
        first_prompt="Start",
        first_keyboard=draft_choice_keyboard(),
        session_expired_msg="Expired",
        draft_used_msg="Draft used",
    )
    assert len(messenger_client.sent_text) >= 2
    assert messenger_client.sent_text[0]["text"] == "Draft used"
    assert messenger_client.sent_text[1]["text"] == "Start"


@pytest.mark.asyncio
async def test_handle_draft_choice_start_over() -> None:
    """When START_OVER, delete draft and show first step."""

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            self.state = state

        async def update_data(self, **kwargs) -> None:
            pass

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="1",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text=START_OVER_BUTTON_TEXT,
    )
    state = FakeState()
    delete_calls = []

    async def mock_delete(*args):  # type: ignore[no-untyped-def]
        delete_calls.append(args)

    async def get_draft(*args):  # type: ignore[no-untyped-def]
        return None

    draft_service = type(
        "S",
        (),
        {"get_draft": get_draft, "delete_draft": mock_delete},
    )()

    await handle_draft_choice(
        message,
        messenger_client,
        state,
        draft_service,
        flow_type="test",
        user_id_key="user_id",
        first_state="FirstState",
        first_prompt="Start",
        first_keyboard=draft_choice_keyboard(),
        session_expired_msg="Expired",
    )
    assert len(delete_calls) == 1
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == "Start"


@pytest.mark.asyncio
async def test_handle_draft_choice_invalid_choice() -> None:
    """When text is neither RESUME nor START_OVER, ask to choose."""

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            pass

        async def update_data(self, **kwargs) -> None:
            pass

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="1",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="invalid",
    )
    state = FakeState()

    async def get_draft(*args):  # type: ignore[no-untyped-def]
        return None

    async def delete_draft(*args):  # type: ignore[no-untyped-def]
        pass

    draft_service = type(
        "S",
        (),
        {"get_draft": get_draft, "delete_draft": delete_draft},
    )()

    await handle_draft_choice(
        message,
        messenger_client,
        state,
        draft_service,
        flow_type="test",
        user_id_key="user_id",
        first_state="FirstState",
        first_prompt="Start",
        first_keyboard=draft_choice_keyboard(),
        session_expired_msg="Expired",
    )
    assert len(messenger_client.sent_text) == 1
    assert (
        "Продолжить" in messenger_client.sent_text[0]["text"]
        or "Начать заново" in messenger_client.sent_text[0]["text"]
    )
