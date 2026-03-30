"""Tests for Max complaints handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.complaints import (
    STATE_COMPLAINT_REASON_TEXT,
    router,
)
from ugc_bot.bot.telegram.handlers.complaints import (
    _COMPLAINT_OTHER_INDEX,
    _COMPLAINT_REASONS,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


def _user(*, status=UserStatus.ACTIVE, user_id=None):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.status = status
    u.username = "alice"
    u.country = "RU"
    return u


def _incoming_cb(data: str) -> IncomingCallback:
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=data,
        message_id="msg_1",
    )


def _incoming_msg(text: str) -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=text,
        message_id="msg_1",
    )


def _deps(
    user=None, *, order=None, state=None, state_data=None, responses=None
):
    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)
    user_role_service.get_user_by_id = AsyncMock(return_value=None)

    if order is None:
        order = MagicMock()
        order.advertiser_id = uuid4()

    order_service = AsyncMock()
    order_service.get_order = AsyncMock(return_value=order)

    offer_response_service = AsyncMock()
    offer_response_service.list_by_order = AsyncMock(
        return_value=responses if responses is not None else []
    )

    state_store = AsyncMock()
    state_store.get_state = AsyncMock(return_value=state)
    state_store.get_data = AsyncMock(return_value=state_data or {})

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "order_service": order_service,
        "offer_response_service": offer_response_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value="text"),
            get_many=AsyncMock(return_value={}),
        ),
        "complaint_service": AsyncMock(),
        "state_store": state_store,
        "locale": "ru",
    }


# ── complaint_select ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complaint_select_user_not_found():
    """Complaint selection with no user answers callback with error."""
    deps = _deps(user=None)
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_blocked_user():
    """Blocked user gets denied via answer_callback."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_pause_user():
    """Paused user gets denied via answer_callback."""
    user = _user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_invalid_format_answers_error():
    """Data with wrong format (missing order_id) answers error."""
    user = _user()
    deps = _deps(user=user)
    # No colon → parts count != 2
    await router.route_callback(_incoming_cb("complaint_select:"), deps)
    # Empty string after split produces parts ["complaint_select", ""]
    # UUID("") raises ValueError → answers error
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_invalid_uuid_answers_error():
    """Invalid UUID in complaint_select answers error."""
    user = _user()
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb("complaint_select:not-a-uuid"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_order_not_found_answers_error():
    """Non-existent order answers not-found callback."""
    user = _user()
    order_service = AsyncMock()
    order_service.get_order = AsyncMock(return_value=None)
    deps = _deps(user=user)
    deps["order_service"] = order_service
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_advertiser_path_no_responses():
    """Advertiser with no responses sees 'no bloggers' message."""
    advertiser_id = uuid4()
    user = _user(user_id=advertiser_id)
    order = MagicMock()
    order.advertiser_id = advertiser_id
    deps = _deps(user=user, order=order, responses=[])
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_advertiser_path_shows_blogger_buttons():
    """Advertiser with responses gets blogger selection keyboard."""
    advertiser_id = uuid4()
    user = _user(user_id=advertiser_id)
    order = MagicMock()
    order.advertiser_id = advertiser_id
    # Create a fake response
    resp = MagicMock()
    resp.blogger_id = uuid4()
    deps = _deps(user=user, order=order, responses=[resp])
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_blogger_path_not_in_responses():
    """Blogger not in order responses gets no-access message."""
    blogger_id = uuid4()
    user = _user(user_id=blogger_id)
    advertiser_id = uuid4()
    order = MagicMock()
    order.advertiser_id = advertiser_id
    # Response belongs to different blogger
    resp = MagicMock()
    resp.blogger_id = uuid4()
    deps = _deps(user=user, order=order, responses=[resp])
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_select_blogger_path_shows_reason_keyboard():
    """Blogger in order responses gets reason selection keyboard."""
    blogger_id = uuid4()
    user = _user(user_id=blogger_id)
    advertiser_id = uuid4()
    order = MagicMock()
    order.advertiser_id = advertiser_id
    resp = MagicMock()
    resp.blogger_id = blogger_id
    deps = _deps(user=user, order=order, responses=[resp])
    order_id = uuid4()
    await router.route_callback(
        _incoming_cb(f"complaint_select:{order_id}"), deps
    )
    deps["messenger_client"].send_text.assert_called()


# ── complaint:{index} ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_complaint_user_not_found():
    """complaint:{i} with no user answers callback error."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb("complaint:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_start_complaint_invalid_index_type():
    """complaint with non-integer index returns early."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb("complaint:abc"), deps)
    # No state change or send_text since index parsing fails
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_start_complaint_session_expired_no_state_data():
    """complaint callback with empty state data sends session-expired."""
    deps = _deps(user=_user(), state_data={})
    await router.route_callback(_incoming_cb("complaint:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_start_complaint_index_out_of_range():
    """complaint callback with index beyond blogger_ids list sends expired."""
    order_id = uuid4()
    blogger_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reporter_id": str(uuid4()),
            "blogger_ids": [str(blogger_id)],
        },
    )
    await router.route_callback(_incoming_cb("complaint:5"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_start_complaint_valid_shows_reason_keyboard():
    """complaint callback with valid index shows reason selection keyboard."""
    order_id = uuid4()
    blogger_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reporter_id": str(uuid4()),
            "blogger_ids": [str(blogger_id)],
        },
    )
    await router.route_callback(_incoming_cb("complaint:0"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_COMPLAINT_REASON_TEXT
    )


# ── complaint_reason:{index} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complaint_reason_empty_state_data_answers_expired():
    """complaint_reason with empty state data answers session-expired."""
    deps = _deps(user=_user(), state_data={})
    await router.route_callback(_incoming_cb("complaint_reason:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_invalid_index_answers_error():
    """complaint_reason with out-of-range index answers invalid-reason."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    await router.route_callback(_incoming_cb("complaint_reason:999"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_missing_ids_answers_data_error():
    """complaint_reason with missing UUIDs in state answers data-error."""
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": "not-a-uuid",
            "reported_id": "x",
            "reporter_id": "y",
        },
    )
    await router.route_callback(_incoming_cb("complaint_reason:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_other_path_prompts_description():
    """'Other' reason index prompts for description text."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    await router.route_callback(
        _incoming_cb(f"complaint_reason:{_COMPLAINT_OTHER_INDEX}"), deps
    )
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_COMPLAINT_REASON_TEXT
    )
    deps["complaint_service"].create_complaint.assert_not_called()


@pytest.mark.asyncio
async def test_complaint_reason_non_other_creates_complaint():
    """Non-other reason creates complaint and notifies admins."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    complaint = MagicMock()
    deps["complaint_service"].create_complaint = AsyncMock(
        return_value=complaint
    )
    # Use index 0 (first non-other reason)
    await router.route_callback(_incoming_cb("complaint_reason:0"), deps)
    deps["complaint_service"].create_complaint.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_value_error_answers_exc_text():
    """ValueError from create_complaint is answered to user."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    deps["complaint_service"].create_complaint = AsyncMock(
        side_effect=ValueError("already exists")
    )
    await router.route_callback(_incoming_cb("complaint_reason:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


# ── STATE_COMPLAINT_REASON_TEXT message handler ───────────────────────────────


@pytest.mark.asyncio
async def test_complaint_reason_text_empty_text_ignored():
    """Empty text input in complaint state is silently ignored."""
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": str(uuid4()),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    incoming = IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=None,
        message_id="msg_1",
    )
    await router.route_message(incoming, deps)
    deps["complaint_service"].create_complaint.assert_not_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_empty_state_sends_expired():
    """Whitespace-only text with empty state sends session-expired."""
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={},
    )
    await router.route_message(_incoming_msg("  "), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_blank_string_re_prompts():
    """Blank (whitespace-only) text re-prompts user to enter reason."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    await router.route_message(_incoming_msg("   "), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["complaint_service"].create_complaint.assert_not_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_invalid_uuids_sends_data_error():
    """Invalid UUIDs in state data sends data-error message."""
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": "bad",
            "reported_id": "bad",
            "reporter_id": "bad",
        },
    )
    await router.route_message(_incoming_msg("Some reason"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["complaint_service"].create_complaint.assert_not_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_creates_complaint():
    """Valid text creates complaint with combined reason."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
            "reason": "Другое",
        },
    )
    complaint = MagicMock()
    deps["complaint_service"].create_complaint = AsyncMock(
        return_value=complaint
    )
    await router.route_message(_incoming_msg("They were rude"), deps)
    deps["complaint_service"].create_complaint.assert_called_once()
    # Reason should be prefixed
    call_kwargs = deps["complaint_service"].create_complaint.call_args.kwargs
    assert (
        "Другое:" in call_kwargs["reason"]
        or "They were rude" in call_kwargs["reason"]
    )
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_value_error_sends_exc_text():
    """ValueError from create_complaint is sent as text and state cleared."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    deps["complaint_service"].create_complaint = AsyncMock(
        side_effect=ValueError("duplicate")
    )
    await router.route_message(_incoming_msg("reason text"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_complaint_reason_text_generic_error_sends_error_later():
    """Generic exception from create_complaint sends generic error message."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_COMPLAINT_REASON_TEXT,
        state_data={
            "order_id": str(order_id),
            "reported_id": str(uuid4()),
            "reporter_id": str(uuid4()),
        },
    )
    deps["complaint_service"].create_complaint = AsyncMock(
        side_effect=RuntimeError("db error")
    )
    await router.route_message(_incoming_msg("reason text"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()


# ── _COMPLAINT_REASONS constant sanity check ─────────────────────────────────


def test_complaint_other_index_is_last():
    """_COMPLAINT_OTHER_INDEX is the last index in _COMPLAINT_REASONS."""
    assert len(_COMPLAINT_REASONS) - 1 == _COMPLAINT_OTHER_INDEX
    assert _COMPLAINT_REASONS[_COMPLAINT_OTHER_INDEX] == "Другое"
