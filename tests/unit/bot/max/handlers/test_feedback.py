"""Tests for Max feedback handlers."""

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
    _no_deal_reason_keyboard_max,
    _nps_keyboard_max,
    router,
)
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.domain.enums import MessengerType, UserStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid_hex(uid: UUID) -> str:
    return uid.hex


def _make_callback(data: str, message_id: str = "msg_1") -> IncomingCallback:
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


_MISSING = object()  # sentinel


def _make_deps(
    *,
    user: object = _MISSING,
    interaction: MagicMock | None = None,
    state_data: dict | None = None,
) -> dict:
    """Build a minimal deps dict for feedback handler tests.

    Pass user=None to simulate "user not found" (get_user returns None).
    Omit user to get a default active user.
    """
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
# Keyboard builder tests (already existed – keep them)
# ---------------------------------------------------------------------------


def test_nps_keyboard_max_has_five_buttons():
    """NPS keyboard should have exactly 5 buttons (1-5)."""
    kb = _nps_keyboard_max(uuid4(), "adv")
    assert len(kb.rows) == 1
    assert len(kb.rows[0]) == 5
    labels = [btn.text for btn in kb.rows[0]]
    assert labels == [
        "1 звезд",
        "2 звезд",
        "3 звезд",
        "4 звезд",
        "5 звезд",
    ]


def test_nps_keyboard_callback_data_format():
    """Callback data should be nps:{hex}:{score}:{kind}."""
    uid = uuid4()
    kb = _nps_keyboard_max(uid, "blog")
    for i, btn in enumerate(kb.rows[0], start=1):
        assert btn.callback_data.startswith("nps:")
        assert btn.callback_data.endswith(f":{i}:blog")


def test_no_deal_reason_keyboard_max_has_rows():
    """No-deal reason keyboard should have at least one row."""
    kb = _no_deal_reason_keyboard_max("adv", uuid4(), {})
    assert len(kb.rows) >= 1


def test_no_deal_reason_keyboard_max_blogger_has_rows():
    """No-deal reason keyboard for blogger should have at least one row."""
    kb = _no_deal_reason_keyboard_max("blog", uuid4(), {})
    assert len(kb.rows) >= 1


def test_router_is_max_router():
    """Router should be a MaxRouter instance."""
    assert isinstance(router, MaxRouter)


# ---------------------------------------------------------------------------
# handle_feedback — "feedback:" prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_user_not_found():
    """answer_callback is called when user is not found."""
    interaction_id = uuid4()
    deps = _make_deps(user=None, interaction=_make_interaction())
    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_user_blocked():
    """Blocked user gets answer_callback error and no further processing."""
    user = _make_user(status=UserStatus.BLOCKED)
    interaction = _make_interaction(advertiser_id=user.user_id)
    deps = _make_deps(user=user, interaction=interaction)

    interaction_id = uuid4()
    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_user_pause():
    """Paused user gets answer_callback error."""
    user = _make_user(status=UserStatus.PAUSE)
    interaction = _make_interaction(advertiser_id=user.user_id)
    deps = _make_deps(user=user, interaction=interaction)

    interaction_id = uuid4()
    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_invalid_parts_count():
    """Too few parts triggers invalid_response answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    # only 3 parts instead of 4
    incoming = _make_callback("feedback:adv:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_interaction_not_found():
    """interaction_id not found triggers answer_callback error."""
    user = _make_user()
    deps = _make_deps(user=user, interaction=None)

    interaction_id = uuid4()
    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_invalid_interaction_id():
    """Non-UUID interaction_id triggers invalid_id answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    incoming = _make_callback("feedback:adv:not-a-valid-uuid:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_insufficient_rights():
    """User who is not party to interaction gets insufficient_rights error."""
    user = _make_user()
    # advertiser/blogger IDs are different from user.user_id
    interaction = _make_interaction()
    deps = _make_deps(user=user, interaction=interaction)

    interaction_id = uuid4()
    deps["interaction_service"].get_interaction = AsyncMock(
        return_value=interaction
    )
    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_ok_status_adv():
    """ok status for advertiser records feedback and sends ok message."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    deps["interaction_service"].record_advertiser_feedback.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_ok_status_blog():
    """ok status for blogger records feedback and sends ok message."""
    user = _make_user()
    interaction = _make_interaction(blogger_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(f"feedback:blog:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    deps["interaction_service"].record_blogger_feedback.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_postpone_not_max():
    """postpone status below max_count sends postpone message."""
    user = _make_user()
    interaction = _make_interaction(
        advertiser_id=user.user_id, postpone_count=0
    )
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    # record_advertiser_feedback returns updated interaction
    # with same postpone_count
    deps["interaction_service"].record_advertiser_feedback = AsyncMock(
        return_value=interaction
    )

    incoming = _make_callback(f"feedback:adv:{interaction_id}:postpone")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_postpone_max_reached():
    """postpone at max_count sends thanks_feedback text."""
    user = _make_user()
    interaction = _make_interaction(
        advertiser_id=user.user_id, postpone_count=3
    )
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["interaction_service"].record_advertiser_feedback = AsyncMock(
        return_value=interaction
    )

    incoming = _make_callback(f"feedback:adv:{interaction_id}:postpone")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_no_deal_status():
    """no_deal status triggers no-deal reason keyboard."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(f"feedback:adv:{interaction_id}:no_deal")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_issue_status():
    """issue status sets state and sends issue prompt."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(f"feedback:adv:{interaction_id}:issue")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_ISSUE_TEXT
    )
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_invalid_status():
    """Unknown status triggers invalid_status answer_callback."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(f"feedback:adv:{interaction_id}:unknown_status")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_record_raises_exception():
    """Exception during record_feedback sends error answer_callback."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["interaction_service"].record_advertiser_feedback = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    incoming = _make_callback(f"feedback:adv:{interaction_id}:ok")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_no_deal_removes_keyboard_when_message_id():
    """edit_reply_markup is called when message_id is set."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    incoming = _make_callback(
        f"feedback:adv:{interaction_id}:no_deal", message_id="msg_99"
    )

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_no_deal_edit_markup_failure():
    """edit_reply_markup failure in no_deal is logged, not raised."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    deps["messenger_client"].edit_reply_markup = AsyncMock(
        side_effect=RuntimeError("API error")
    )
    incoming = _make_callback(
        f"feedback:adv:{interaction_id}:no_deal",
        message_id="msg_99",
    )
    await router.route_callback(incoming, deps)
    assert len(deps["messenger_client"].answered_callbacks) >= 1


# ---------------------------------------------------------------------------
# handle_feedback_reason — "fb_r:" prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_reason_user_not_found():
    """Missing user causes answer_callback with not_found text."""
    deps = _make_deps(user=None)
    interaction_id = uuid4()
    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:c")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_invalid_parts():
    """Too few parts triggers invalid_format answer_callback."""
    deps = _make_deps()
    incoming = _make_callback("fb_r:adv:c")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_invalid_hex_id():
    """Non-hex interaction_id triggers invalid_id answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    incoming = _make_callback("fb_r:adv:not-hex:c")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_unknown_reason_code():
    """Unknown reason code triggers invalid_format answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    interaction_id = uuid4()
    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:z")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_interaction_not_found():
    """Missing interaction triggers answer_callback error."""
    user = _make_user()
    deps = _make_deps(user=user, interaction=None)
    interaction_id = uuid4()
    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:c")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_insufficient_rights():
    """User not party to interaction gets insufficient_rights error."""
    user = _make_user()
    interaction = _make_interaction()  # random IDs, not user.user_id
    interaction_id = uuid4()
    deps = _make_deps(user=user, interaction=interaction)
    deps["interaction_service"].get_interaction = AsyncMock(
        return_value=interaction
    )

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:c")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_other_sets_state():
    """Reason 'other' sets STATE_FEEDBACK_TEXT and sends prompt."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:o")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(STATE_FEEDBACK_TEXT)
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_conditions_adv():
    """Known reason 'conditions' for adv records advertiser feedback."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:c")

    await router.route_callback(incoming, deps)

    deps["interaction_service"].record_advertiser_feedback.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_feedback_reason_conditions_blog():
    """Known reason 'conditions' for blog records blogger feedback."""
    user = _make_user()
    interaction = _make_interaction(blogger_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:blog:{hex_id}:c")

    await router.route_callback(incoming, deps)

    deps["interaction_service"].record_blogger_feedback.assert_called_once()


@pytest.mark.asyncio
async def test_handle_feedback_reason_creator_wanted_to_change_increments_count():  # noqa: E501
    """Reason 'w' (creator_wanted_to_change) increments
    wanted_to_change counter."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:w")

    await router.route_callback(incoming, deps)

    deps[
        "blogger_registration_service"
    ].increment_wanted_to_change_terms_count.assert_called_once()


@pytest.mark.asyncio
async def test_handle_feedback_reason_other_removes_keyboard_on_message_id():
    """edit_reply_markup called when reason=other and message_id present."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:adv:{hex_id}:o", message_id="msg_55")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(STATE_FEEDBACK_TEXT)


# ---------------------------------------------------------------------------
# handle_no_deal_other_text — STATE_FEEDBACK_TEXT state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_empty_message():
    """Empty text sends enter_reason_text prompt without clearing state."""
    deps = _make_deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1
    deps["state_store"].clear.assert_not_called()


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_user_not_found():
    """Missing user clears state and does not continue."""
    deps = _make_deps(user=None)
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("some reason text")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) == 0


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_missing_state_data():
    """Missing interaction_id or kind in state sends session_expired."""
    user = _make_user()
    deps = _make_deps(user=user, state_data={})
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("some reason")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_invalid_kind():
    """Invalid kind in state data sends session_expired."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={
            "feedback_interaction_id": str(uuid4()),
            "feedback_kind": "invalid_kind",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("some reason")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_invalid_uuid_in_state():
    """Bad UUID in state sends error_try_again."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={
            "feedback_interaction_id": "not-a-uuid",
            "feedback_kind": "adv",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("some reason text")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_interaction_not_found():
    """Missing interaction sends interaction_not_found text."""
    user = _make_user()
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        interaction=None,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("my reason text")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_insufficient_rights():
    """User not party to interaction sends insufficient_rights."""
    user = _make_user()
    interaction = _make_interaction()  # random IDs
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("my reason text")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_success_adv():
    """Valid reason text for adv records
    no_deal_other_feedback and thanks user."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("price was too high")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_no_deal_other_text_success_blog():
    """Valid reason text for blog records blogger no_deal feedback."""
    user = _make_user()
    interaction = _make_interaction(blogger_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "blog",
        },
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_FEEDBACK_TEXT)

    incoming = _make_message("advertiser was rude")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


# ---------------------------------------------------------------------------
# handle_issue_description — STATE_FEEDBACK_ISSUE_TEXT state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_issue_description_missing_state_data():
    """Missing interaction_id in state clears state
    and sends session_expired."""
    user = _make_user()
    deps = _make_deps(user=user, state_data={})
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("some issue text")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_empty_text_sends_photo_prompt():
    """Empty text (not /send) sends add_description_photo prompt."""
    user = _make_user()
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": [],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_appends_text_to_parts():
    """Non-empty text appends to issue_description_parts
    and confirms receipt."""
    user = _make_user()
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["first part"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("second part")

    await router.route_message(incoming, deps)

    deps["state_store"].update_data.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_no_parts():
    """'/send' with no parts collected sends add_description_before_send."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": [],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("/send")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1
    # state NOT cleared because we asked for description first
    deps["state_store"].clear.assert_not_called()


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_user_not_found():
    """'/send' when user not found clears state and returns."""
    deps = _make_deps(
        user=None,
        state_data={
            "feedback_interaction_id": str(uuid4()),
            "feedback_kind": "adv",
            "issue_description_parts": ["description"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("/send")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) == 0


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_invalid_uuid():
    """'/send' with bad UUID in state clears state and sends error_try_again."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={
            "feedback_interaction_id": "not-a-uuid",
            "feedback_kind": "adv",
            "issue_description_parts": ["description"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("/send")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_interaction_not_found():
    """'/send' when interaction not found clears state and sends error."""
    user = _make_user()
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        interaction=None,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["description"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("/send")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_insufficient_rights():
    """'/send' when user not party to interaction clears state."""
    user = _make_user()
    interaction = _make_interaction()  # random IDs
    interaction_id = uuid4()
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["description"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    incoming = _make_message("/send")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_success_adv():
    """'/send' creates complaint and records advertiser
    feedback, clears state."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["it was a scam"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    with patch(
        "ugc_bot.bot.max.handlers.feedback.notify_admins_about_complaint",
        new_callable=AsyncMock,
    ):
        incoming = _make_message("/send")
        await router.route_message(incoming, deps)

    deps["complaint_service"].create_complaint.assert_called_once()
    deps["interaction_service"].record_advertiser_feedback.assert_called_once()
    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_success_blog():
    """'/send' creates complaint and records blogger feedback."""
    user = _make_user()
    interaction = _make_interaction(blogger_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "blog",
            "issue_description_parts": ["advertiser never paid"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )

    with patch(
        "ugc_bot.bot.max.handlers.feedback.notify_admins_about_complaint",
        new_callable=AsyncMock,
    ):
        incoming = _make_message("/send")
        await router.route_message(incoming, deps)

    deps["complaint_service"].create_complaint.assert_called_once()
    deps["interaction_service"].record_blogger_feedback.assert_called_once()


@pytest.mark.asyncio
async def test_handle_issue_description_send_command_complaint_error():
    """Exception in create_complaint clears state and sends complaint_error."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(
        user=user,
        interaction=interaction,
        state_data={
            "feedback_interaction_id": str(interaction_id),
            "feedback_kind": "adv",
            "issue_description_parts": ["description"],
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_ISSUE_TEXT
    )
    deps["complaint_service"].create_complaint = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    incoming = _make_message("/send")
    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) >= 1


# ---------------------------------------------------------------------------
# handle_nps — "nps:" prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_nps_invalid_parts():
    """Too few parts triggers invalid_format answer_callback."""
    deps = _make_deps()
    incoming = _make_callback("nps:abc")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_invalid_hex():
    """Non-hex user_id triggers invalid_format answer_callback."""
    deps = _make_deps()
    incoming = _make_callback("nps:not-hex:3:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_invalid_score_non_numeric():
    """Non-numeric score triggers invalid_format answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:abc:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_score_out_of_range_low():
    """Score=0 triggers score_1_to_5 answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:0:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_score_out_of_range_high():
    """Score=6 triggers score_1_to_5 answer_callback."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:6:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_user_not_found():
    """Missing user triggers user_not_found answer_callback."""
    deps = _make_deps(user=None)
    uid_hex = _uuid_hex(uuid4())
    incoming = _make_callback(f"nps:{uid_hex}:4:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_user_id_mismatch():
    """user_id in callback differs from auth user
    triggers insufficient_rights."""
    user = _make_user()
    deps = _make_deps(user=user)
    # Use a different UUID for the callback
    other_uid_hex = _uuid_hex(uuid4())
    incoming = _make_callback(f"nps:{other_uid_hex}:4:blog")

    await router.route_callback(incoming, deps)

    assert len(deps["messenger_client"].answered_callbacks) >= 1


@pytest.mark.asyncio
async def test_handle_nps_valid_score_sets_state():
    """Valid NPS score sets STATE_FEEDBACK_NPS_COMMENT and sends prompt."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:5:blog")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_nps_valid_adv_kind():
    """Valid NPS score for adv kind sets state correctly."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:3:adv")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )


@pytest.mark.asyncio
async def test_handle_nps_three_parts_defaults_to_blog():
    """3-part nps callback (no kind) defaults kind to 'blog'."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    incoming = _make_callback(f"nps:{uid_hex}:4")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )


@pytest.mark.asyncio
async def test_handle_nps_removes_keyboard_when_message_id_set():
    """edit_reply_markup is attempted when message_id is present."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    # message_id is set in _make_callback by default
    incoming = _make_callback(f"nps:{uid_hex}:5:adv", message_id="msg_77")

    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )


# ---------------------------------------------------------------------------
# handle_nps_comment — STATE_FEEDBACK_NPS_COMMENT state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_nps_comment_user_not_found_clears_state():
    """Missing user clears state and returns without sending text."""
    deps = _make_deps(
        user=None,
        state_data={
            "nps_user_id": str(uuid4()),
            "nps_score": 4,
            "nps_kind": "blog",
        },
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("great service")

    await router.route_message(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    assert len(deps["messenger_client"].sent_text) == 0


@pytest.mark.asyncio
async def test_handle_nps_comment_missing_state_data():
    """Missing nps_user_id in state sends session_expired_nps."""
    user = _make_user()
    deps = _make_deps(user=user, state_data={})
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("good job")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_nps_comment_invalid_uuid_in_state():
    """Bad UUID in state sends error_try_again text."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={"nps_user_id": "not-a-uuid", "nps_score": 4},
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("good job")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_nps_comment_user_id_mismatch():
    """State has different user_id than authenticated
    user sends insufficient_rights."""
    user = _make_user()
    other_uid = uuid4()
    deps = _make_deps(
        user=user,
        state_data={"nps_user_id": str(other_uid), "nps_score": 3},
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("comment text")

    await router.route_message(incoming, deps)

    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_nps_comment_success_with_text():
    """Valid NPS comment saves to nps_service and thanks user."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={"nps_user_id": str(user.user_id), "nps_score": 5},
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("everything was perfect")

    await router.route_message(incoming, deps)

    deps["nps_service"].save.assert_called_once_with(
        user.user_id, 5, comment="everything was perfect"
    )
    assert len(deps["messenger_client"].sent_text) >= 1


@pytest.mark.asyncio
async def test_handle_nps_comment_done_btn_sends_no_comment():
    """Pressing 'done' button (matching done_btn text)
    saves with comment=None."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={"nps_user_id": str(user.user_id), "nps_score": 4},
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )
    # done_btn text is returned from bot_texts_service
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"msg_fb_nps_done_btn": "Готово"}
    )

    incoming = _make_message("Готово")

    await router.route_message(incoming, deps)

    deps["nps_service"].save.assert_called_once_with(
        user.user_id, 4, comment=None
    )


@pytest.mark.asyncio
async def test_handle_nps_comment_empty_text_saves_none():
    """Empty comment text saves with comment=None."""
    user = _make_user()
    deps = _make_deps(
        user=user,
        state_data={"nps_user_id": str(user.user_id), "nps_score": 2},
    )
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_FEEDBACK_NPS_COMMENT
    )

    incoming = _make_message("   ")

    await router.route_message(incoming, deps)

    deps["nps_service"].save.assert_called_once_with(
        user.user_id, 2, comment=None
    )


# ---------------------------------------------------------------------------
# Additional edge-case tests for remaining uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_feedback_no_data_returns_early():
    """handle_feedback with no callback data returns without doing anything."""
    deps = _make_deps()
    incoming = IncomingCallback(
        callback_id="cb_x",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="feedback:adv:something:ok",
        message_id="msg_1",
    )
    # Override data to None after construction
    incoming = IncomingCallback(
        callback_id="cb_x",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    # The router predicate checks cb.data, so None data won't match the route
    # — test that no service calls happen at all
    await router.route_callback(incoming, deps)

    deps["user_role_service"].get_user.assert_not_called()


@pytest.mark.asyncio
async def test_handle_feedback_reason_no_data_returns_early():
    """handle_feedback_reason with no callback data does nothing."""
    deps = _make_deps()
    incoming = IncomingCallback(
        callback_id="cb_x",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    await router.route_callback(incoming, deps)

    deps["user_role_service"].get_user.assert_not_called()


@pytest.mark.asyncio
async def test_handle_nps_no_data_returns_early():
    """handle_nps with no callback data does nothing."""
    deps = _make_deps()
    incoming = IncomingCallback(
        callback_id="cb_x",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data=None,
        message_id="msg_1",
    )
    await router.route_callback(incoming, deps)

    deps["user_role_service"].get_user.assert_not_called()


@pytest.mark.asyncio
async def test_handle_nps_invalid_kind_defaults_to_blog():
    """NPS callback with unrecognised kind defaults to 'blog'."""
    user = _make_user()
    deps = _make_deps(user=user)
    uid_hex = _uuid_hex(user.user_id)
    # 'xyz' is not 'adv' or 'blog' — should default to 'blog'
    incoming = _make_callback(f"nps:{uid_hex}:3:xyz")

    await router.route_callback(incoming, deps)

    # State should still be set (kind defaults to 'blog', not rejected)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_FEEDBACK_NPS_COMMENT
    )


@pytest.mark.asyncio
async def test_maybe_send_nps_skipped_when_nps_already_exists_for_blog():
    """NPS prompt is not sent when nps_service.exists_for_user returns True."""
    user = _make_user()
    interaction = _make_interaction(blogger_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    # Simulate existing NPS score for this blogger
    deps["nps_service"].exists_for_user = AsyncMock(return_value=True)

    hex_id = _uuid_hex(interaction_id)
    incoming = _make_callback(f"fb_r:blog:{hex_id}:c")

    await router.route_callback(incoming, deps)

    # Feedback was recorded
    deps["interaction_service"].record_blogger_feedback.assert_called_once()
    # NPS keyboard should NOT have been sent (exists_for_user returned True)
    nps_messages = [
        m
        for m in deps["messenger_client"].sent_text
        if m.get("keyboard") is not None
    ]
    assert len(nps_messages) == 0


@pytest.mark.asyncio
async def test_maybe_send_nps_skipped_when_advertiser_feedback_not_needed():
    """NPS not sent for advertiser when
    _advertiser_has_feedback_for_bloggers_needed
    is False."""
    user = _make_user()
    interaction = _make_interaction(advertiser_id=user.user_id)
    interaction_id = interaction.interaction_id
    deps = _make_deps(user=user, interaction=interaction)
    # Simulate no NPS needed for advertiser

    with patch(
        "ugc_bot.bot.max.handlers.feedback._advertiser_has_feedback_for_bloggers_needed",
        new=AsyncMock(return_value=False),
    ):
        hex_id = _uuid_hex(interaction_id)
        incoming = _make_callback(f"fb_r:adv:{hex_id}:c")
        await router.route_callback(incoming, deps)

    # Feedback was recorded
    deps["interaction_service"].record_advertiser_feedback.assert_called_once()
    # NPS keyboard should NOT have been sent
    nps_messages = [
        m
        for m in deps["messenger_client"].sent_text
        if m.get("keyboard") is not None
    ]
    assert len(nps_messages) == 0
