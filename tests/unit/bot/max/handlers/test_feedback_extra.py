"""Extra tests for Max feedback handlers covering remaining uncovered lines."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.feedback import (
    STATE_FEEDBACK_ISSUE_TEXT,
    STATE_FEEDBACK_NPS_COMMENT,
    STATE_FEEDBACK_TEXT,
    router,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


def _uuid_hex(uid: UUID) -> str:
    return uid.hex


def _make_callback(
    data: str | None, message_id: str = "msg_1"
) -> IncomingCallback:
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=data,
        message_id=message_id,
    )


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=text,
        message_id="msg_2",
    )


def _make_user(
    *,
    user_id: UUID | None = None,
    status: UserStatus = UserStatus.ACTIVE,
) -> MagicMock:
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.status = status
    return u


def _make_interaction(
    *,
    interaction_id: UUID | None = None,
    advertiser_id: UUID | None = None,
    blogger_id: UUID | None = None,
    order_id: UUID | None = None,
    postpone_count: int = 0,
) -> MagicMock:
    ia = MagicMock()
    ia.interaction_id = interaction_id or uuid4()
    ia.advertiser_id = advertiser_id or uuid4()
    ia.blogger_id = blogger_id or uuid4()
    ia.order_id = order_id or uuid4()
    ia.postpone_count = postpone_count
    return ia


_MISSING = object()


def _make_deps(
    *,
    user: object = _MISSING,
    interaction: MagicMock | None = None,
    state_data: dict | None = None,
) -> dict:
    from tests.helpers.fakes import FakeMessengerClient

    if user is _MISSING:
        user = _make_user()

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    interaction_service = AsyncMock()
    interaction_service.get_interaction = AsyncMock(return_value=interaction)
    interaction_service.record_advertiser_feedback = AsyncMock(
        return_value=interaction
    )
    interaction_service.record_blogger_feedback = AsyncMock(
        return_value=interaction
    )
    interaction_service.max_postpone_count = 3

    nps_service = AsyncMock()
    nps_service.exists_for_user = AsyncMock(return_value=False)
    nps_service.save = AsyncMock()

    order_service = AsyncMock()

    blogger_reg_service = AsyncMock()
    blogger_reg_service.increment_wanted_to_change_terms_count = AsyncMock()

    complaint_service = AsyncMock()
    complaint_service.create_complaint = AsyncMock(return_value=MagicMock())

    state_store = AsyncMock()
    state_store.get_state = AsyncMock(return_value=None)
    state_store.set_state = AsyncMock()
    state_store.update_data = AsyncMock()
    state_store.clear = AsyncMock()
    state_store.get_data = AsyncMock(return_value=state_data or {})

    bot_texts_service = AsyncMock()
    bot_texts_service.get = AsyncMock(return_value="")
    bot_texts_service.get_many = AsyncMock(return_value={})

    return {
        "messenger_client": FakeMessengerClient(),
        "telegram_messenger_client": FakeMessengerClient(),
        "user_role_service": user_role_service,
        "interaction_service": interaction_service,
        "nps_service": nps_service,
        "order_service": order_service,
        "blogger_registration_service": blogger_reg_service,
        "complaint_service": complaint_service,
        "state_store": state_store,
        "bot_texts_service": bot_texts_service,
        "locale": "ru",
    }


# ---------------------------------------------------------------------------
# handle_feedback — if not incoming.data guard (line 396)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_no_data_returns_early() -> None:
    """handle_feedback returns early when incoming.data is None."""
    deps = _make_deps()
    # "feedback:" prefix matches the router; data=None triggers guard
    incoming = _make_callback(None)
    # Override data to None for a callback that would match feedback:
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
    # Route directly to handle_feedback by importing and calling it
    from ugc_bot.bot.max.handlers.feedback import handle_feedback

    await handle_feedback(incoming, deps)
    # No calls should have been made because of early return
    deps["user_role_service"].get_user.assert_not_called()


# ---------------------------------------------------------------------------
# handle_feedback_reason — if not incoming.data guard (line 608)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_reason_no_data_returns_early() -> None:
    """handle_feedback_reason returns early when incoming.data is None."""
    deps = _make_deps()
    from ugc_bot.bot.max.handlers.feedback import handle_feedback_reason

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
    await handle_feedback_reason(incoming, deps)
    deps["user_role_service"].get_user.assert_not_called()


# ---------------------------------------------------------------------------
# handle_nps — if not incoming.data guard (line 984)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_nps_no_data_returns_early() -> None:
    """handle_nps returns early when incoming.data is None."""
    deps = _make_deps()
    from ugc_bot.bot.max.handlers.feedback import handle_nps

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
    await handle_nps(incoming, deps)
    deps["user_role_service"].get_user.assert_not_called()


# ---------------------------------------------------------------------------
# NPS send for advertiser when feedback is needed (line 116)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nps_sent_for_advertiser_when_feedback_needed() -> None:
    """NPS keyboard sent for advertiser when all bloggers gave feedback."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    with patch(
        "ugc_bot.bot.max.handlers.feedback._advertiser_has_feedback_for_bloggers_needed",
        new=AsyncMock(return_value=True),
    ):
        hex_id = _uuid_hex(interaction_id)
        incoming = _make_callback(f"fb_r:adv:{hex_id}:c")
        await router.route_callback(incoming, deps)

    # Feedback was recorded
    deps["interaction_service"].record_advertiser_feedback.assert_called_once()
    # NPS keyboard should have been sent for advertiser
    nps_messages = [
        m
        for m in deps["messenger_client"].sent_text
        if m.get("keyboard") is not None
    ]
    assert len(nps_messages) >= 1


# ---------------------------------------------------------------------------
# _send_feedback_response — else branch (lines 267-271)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_feedback_response_else_branch() -> None:
    """The else branch in _send_feedback_response sends thanks_saved."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.bot.max.handlers.feedback import _send_feedback_response

    messenger = FakeMessengerClient()
    interaction = _make_interaction()
    interaction_service = AsyncMock()
    interaction_service.max_postpone_count = 3
    nps_service = AsyncMock()
    nps_service.exists_for_user = AsyncMock(return_value=False)
    order_service = AsyncMock()

    incoming = _make_callback("feedback:blog:someid:somestatus")

    # Call with status_raw that is not "postpone" or "ok"
    await _send_feedback_response(
        incoming=incoming,
        kind="blog",
        status_raw="some_other_status",
        updated=interaction,
        messenger_client=messenger,
        interaction_service=interaction_service,
        nps_service=nps_service,
        order_service=order_service,
        texts={},
    )
    # should have some response: answer_callback or send_text
    assert (
        len(messenger.answered_callbacks) >= 1 or len(messenger.sent_text) >= 1
    )


# ---------------------------------------------------------------------------
# _handle_feedback_issue — edit_reply_markup exception (lines 183-184)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_issue_edit_markup_failure() -> None:
    """edit_reply_markup failure in issue handler is swallowed."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )

    incoming = _make_callback(
        f"feedback:adv:{interaction_id}:issue",
        message_id="msg_99",
    )

    await router.route_callback(incoming, deps)

    # state should still be set despite edit_reply_markup failure
    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_ISSUE_TEXT
    )


# ---------------------------------------------------------------------------
# _send_feedback_response — edit_reply_markup exception (lines 249-250)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_feedback_response_edit_markup_failure() -> None:
    """edit_reply_markup failure in _send_feedback_response is swallowed."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )

    incoming = _make_callback(
        f"feedback:adv:{interaction_id}:ok",
        message_id="msg_99",
    )

    await router.route_callback(incoming, deps)

    # feedback should still be recorded despite markup failure
    deps["interaction_service"].record_advertiser_feedback.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_reason_other — edit_reply_markup exception (lines 515-516)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_reason_other_edit_markup_failure() -> None:
    """edit_reply_markup failure in _handle_reason_other is swallowed."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:o", message_id="msg_99")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(STATE_FEEDBACK_TEXT)


# ---------------------------------------------------------------------------
# _record_reason_and_respond — edit_reply_markup exception (lines 565-566)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_reason_respond_edit_markup_failure() -> None:
    """edit_reply_markup failure in _record_reason_and_respond is swallowed."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:c", message_id="msg_99")

    await router.route_callback(incoming, deps)

    deps["interaction_service"].record_advertiser_feedback.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_issue_submit — admin notification exception (lines 877-878)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_issue_submit_notify_admins_exception_swallowed() -> None:
    """Exception in notify_admins_about_complaint is swallowed."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["Some issue text"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    with patch(
        "ugc_bot.bot.max.handlers.feedback.notify_admins_about_complaint",
        new=AsyncMock(side_effect=RuntimeError("notify failed")),
    ):
        await router.route_message(_make_message("/send"), deps)

    # The complaint should still be created
    deps["complaint_service"].create_complaint.assert_called_once()
    # State should be cleared
    deps["state_store"].clear.assert_called()


# ---------------------------------------------------------------------------
# handle_nps — edit_reply_markup exception (lines 1056-1057)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_nps_edit_markup_failure() -> None:
    """edit_reply_markup failure in handle_nps is swallowed."""
    user = _make_user()
    deps = _make_deps(user=user)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )

    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:3:blog", message_id="msg_99")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )
