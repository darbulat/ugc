"""Extra tests for Max complaints handlers — remaining uncovered lines."""

from unittest.mock import AsyncMock, MagicMock, patch
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
from ugc_bot.domain.enums import MessengerType, UserStatus


def _user(*, status=UserStatus.ACTIVE, user_id=None):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.status = status
    u.username = "alice"
    return u


def _incoming_cb(data: str | None) -> IncomingCallback:
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
        "telegram_messenger_client": AsyncMock(),
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


# ---------------------------------------------------------------------------
# select_complaint_target — if not incoming.data guard (line 159)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_complaint_target_no_data_returns_early() -> None:
    """select_complaint_target returns early when data is None."""
    from ugc_bot.bot.max.handlers.complaints import select_complaint_target

    deps = _deps(user=_user())
    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    await select_complaint_target(incoming, deps)
    deps["user_role_service"].get_user.assert_not_called()


# ---------------------------------------------------------------------------
# select_complaint_target — invalid format with > 2 parts (lines 190-196)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_complaint_target_too_many_parts_answers_invalid() -> None:
    """select_complaint_target sends error when data has too many colons."""
    from ugc_bot.bot.max.handlers.complaints import select_complaint_target

    user = _user()
    deps = _deps(user=user)
    # complaint_select:extra:parts has 3 parts
    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="complaint_select:a:b",
        message_id="msg_1",
    )
    await select_complaint_target(incoming, deps)
    deps["messenger_client"].answer_callback.assert_called()


# ---------------------------------------------------------------------------
# start_complaint — if not incoming.data guard (line 259)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_complaint_no_data_returns_early() -> None:
    """start_complaint returns early when data is None."""
    from ugc_bot.bot.max.handlers.complaints import start_complaint

    deps = _deps(user=_user())
    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    await start_complaint(incoming, deps)
    deps["user_role_service"].get_user.assert_not_called()


# ---------------------------------------------------------------------------
# start_complaint — ValueError when parsing UUID (lines 303-304)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_complaint_invalid_uuid_in_blogger_ids_returns_early() -> (
    None
):
    """start_complaint returns early when a blogger_id is not a valid UUID."""
    from ugc_bot.bot.max.handlers.complaints import start_complaint

    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state_data={
            "order_id": str(order_id),
            "reporter_id": str(uuid4()),
            "blogger_ids": ["not-a-uuid"],  # invalid UUID
        },
    )
    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="complaint:0",
        message_id="msg_1",
    )
    await start_complaint(incoming, deps)
    # Returns early without sending anything
    deps["messenger_client"].send_text.assert_not_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# handle_complaint_reason — if not incoming.data guard (line 345)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_complaint_reason_no_data_returns_early() -> None:
    """handle_complaint_reason returns early when data is None."""
    from ugc_bot.bot.max.handlers.complaints import handle_complaint_reason

    deps = _deps(user=_user(), state_data={"order_id": str(uuid4())})
    incoming = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    await handle_complaint_reason(incoming, deps)
    deps["state_store"].get_data.assert_not_called()


# ---------------------------------------------------------------------------
# handle_complaint_reason — generic exception from create_complaint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_complaint_reason_generic_exception_answers_error() -> (
    None
):
    """Generic exception from create_complaint answers error message."""
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
        side_effect=RuntimeError("db timeout")
    )
    await router.route_callback(_incoming_cb("complaint_reason:0"), deps)
    deps["messenger_client"].answer_callback.assert_called()


# ---------------------------------------------------------------------------
# handle_complaint_reason — notify_admins exception swallowed (lines 421-422)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_complaint_reason_notify_exception_swallowed() -> None:
    """Exception from notify_admins in handle_complaint_reason is swallowed."""
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

    with patch(
        "ugc_bot.bot.max.handlers.complaints.notify_admins_about_complaint",
        new=AsyncMock(side_effect=RuntimeError("notify error")),
    ):
        await router.route_callback(_incoming_cb("complaint_reason:0"), deps)

    deps["complaint_service"].create_complaint.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# handle_complaint_reason_text — notify_admins exception swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complaint_reason_text_notify_exception_swallowed() -> None:
    """Exception from notify_admins in reason_text handler is swallowed."""
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

    with patch(
        "ugc_bot.bot.max.handlers.complaints.notify_admins_about_complaint",
        new=AsyncMock(side_effect=RuntimeError("notify error")),
    ):
        await router.route_message(_incoming_msg("Some reason text"), deps)

    deps["complaint_service"].create_complaint.assert_called_once()
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()
