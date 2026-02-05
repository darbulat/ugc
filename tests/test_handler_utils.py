"""Tests for handler utilities."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.bot.handlers.keyboards import (
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
    draft_choice_keyboard,
)
from ugc_bot.bot.handlers.utils import (
    RateLimiter,
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

    class DummyBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls += 1

    bot = DummyBot()
    ok = await send_with_retry(
        bot,
        chat_id=1,
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is True
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_send_with_retry_failure() -> None:
    """Return False after retries exhausted."""

    class DummyBot:
        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("fail")

    ok = await send_with_retry(
        DummyBot(),
        chat_id=1,
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


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_none() -> None:
    """When user is None, send user_not_found_msg and return None."""

    class FakeMessage:
        from_user = type("U", (), {"id": 123})()

        def __init__(self) -> None:
            self.answers = []

        async def answer(self, text: str) -> None:
            self.answers.append(text)

    class NoUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> None:
            return None

    message = FakeMessage()
    result = await get_user_and_ensure_allowed(
        message,
        NoUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert message.answers == ["Not found"]


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_blocked() -> None:
    """When user is BLOCKED, send blocked_msg and return None."""

    class FakeMessage:
        from_user = type("U", (), {"id": 456})()

        def __init__(self) -> None:
            self.answers = []

        async def answer(self, text: str) -> None:
            self.answers.append(text)

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

    message = FakeMessage()
    result = await get_user_and_ensure_allowed(
        message,
        BlockedUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert message.answers == ["Blocked"]


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_ok() -> None:
    """When user is allowed, return user."""

    class FakeMessage:
        from_user = type("U", (), {"id": 789})()

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

    message = FakeMessage()
    result = await get_user_and_ensure_allowed(
        message,
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

    class FakeCallback:
        from_user = type("U", (), {"id": 999})()

        def __init__(self) -> None:
            self.answers = []

        async def answer(self, text: str) -> None:
            self.answers.append(text)

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

    callback = FakeCallback()
    result = await get_user_and_ensure_allowed_callback(
        callback,
        OkUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is ok_user
    assert len(callback.answers) == 0


@pytest.mark.asyncio
async def test_handle_draft_choice_session_expired() -> None:
    """When user_id missing from state, clear and send session_expired_msg."""

    class FakeMessage:
        def __init__(self) -> None:
            self.text = ""
            self.answers = []

        async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
            self.answers.append((text, reply_markup))

    class FakeState:
        async def get_data(self) -> dict:
            return {}

        async def clear(self) -> None:
            self.cleared = True

        async def set_state(self, state) -> None:
            pass

        async def update_data(self, **kwargs) -> None:
            pass

    message = FakeMessage()
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
    assert len(message.answers) == 1
    assert message.answers[0][0] == "Session expired"


@pytest.mark.asyncio
async def test_handle_draft_choice_resume_draft_none() -> None:
    """When RESUME_DRAFT but draft None, show draft_used_msg and first step."""

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.answers = []

        async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
            self.answers.append((text, reply_markup))

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            self.state = state

        async def update_data(self, **kwargs) -> None:
            pass

    message = FakeMessage(RESUME_DRAFT_BUTTON_TEXT)
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
    assert len(message.answers) >= 2
    assert message.answers[0][0] == "Draft used"
    assert message.answers[1][0] == "Start"


@pytest.mark.asyncio
async def test_handle_draft_choice_start_over() -> None:
    """When START_OVER, delete draft and show first step."""

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.answers = []

        async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
            self.answers.append((text, reply_markup))

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            self.state = state

        async def update_data(self, **kwargs) -> None:
            pass

    message = FakeMessage(START_OVER_BUTTON_TEXT)
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
    assert len(message.answers) == 1
    assert message.answers[0][0] == "Start"


@pytest.mark.asyncio
async def test_handle_draft_choice_invalid_choice() -> None:
    """When text is neither RESUME nor START_OVER, ask to choose."""

    class FakeMessage:
        def __init__(self, text: str) -> None:
            self.text = text
            self.answers = []

        async def answer(self, text: str, reply_markup=None, **kwargs) -> None:
            self.answers.append((text, reply_markup))

    class FakeState:
        async def get_data(self) -> dict:
            return {"user_id": str(uuid4())}

        async def clear(self) -> None:
            pass

        async def set_state(self, state) -> None:
            pass

        async def update_data(self, **kwargs) -> None:
            pass

    message = FakeMessage("invalid")
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
        state,
        draft_service,
        flow_type="test",
        user_id_key="user_id",
        first_state="FirstState",
        first_prompt="Start",
        first_keyboard=draft_choice_keyboard(),
        session_expired_msg="Expired",
    )
    assert len(message.answers) == 1
    assert (
        "Продолжить" in message.answers[0][0]
        or "Начать заново" in message.answers[0][0]
    )
