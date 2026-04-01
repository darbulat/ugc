"""Tests for Max offer responses handlers."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.offer_responses import (
    STATE_WAITING_DESIRED_PRICE,
    router,
)
from ugc_bot.domain.enums import MessengerType, RejectionReason, UserStatus


def _user(*, status=UserStatus.ACTIVE):
    u = MagicMock()
    u.user_id = uuid4()
    u.status = status
    u.username = "alice"
    u.country = "RU"
    return u


def _incoming_cb(
    data: str, *, message_id: str | None = "msg_1"
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


def _deps(user=None, *, blogger_profile=None, state=None, state_data=None):
    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)
    user_role_service.get_user_by_id = AsyncMock(return_value=None)

    profile_service = AsyncMock()
    if blogger_profile is not None:
        profile_service.get_blogger_profile = AsyncMock(
            return_value=blogger_profile
        )
    else:
        profile_service.get_blogger_profile = AsyncMock(return_value=None)

    state_store = AsyncMock()
    state_store.get_state = AsyncMock(return_value=state)
    state_store.get_data = AsyncMock(return_value=state_data or {})

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value="text"),
            get_many=AsyncMock(return_value={}),
        ),
        "offer_dispatch_service": AsyncMock(),
        "offer_response_service": AsyncMock(),
        "profile_service": profile_service,
        "interaction_service": AsyncMock(),
        "state_store": state_store,
        "config": MagicMock(market=MagicMock(currency_symbol="₽")),
        "locale": "ru",
    }


# ── _safe_clear_markup ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_clear_markup_logs_on_failure():
    """edit_reply_markup failure is logged, not raised."""
    from ugc_bot.bot.max.handlers.offer_responses import (
        _safe_clear_markup,
    )

    client = AsyncMock()
    client.edit_reply_markup = AsyncMock(side_effect=RuntimeError("API down"))
    # Should not raise
    await _safe_clear_markup(client, "chat", "msg")
    client.edit_reply_markup.assert_called_once()


# ── offer_skip ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_offer_skip_user_not_found():
    """Skip with no user sends skipped message and answers callback."""
    order_id = uuid4()
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(f"offer_skip:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_offer_skip_with_valid_user_shows_reason_menu():
    """Skip with valid user shows rejection reason buttons."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(f"offer_skip:{order_id}"), deps)
    deps["messenger_client"].send_text.assert_called()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_offer_skip_invalid_order_id_returns_early():
    """Skip with invalid UUID returns early after answering callback."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb("offer_skip:not-a-uuid"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    # No reason menu shown since order_id is None
    deps["messenger_client"].send_text.assert_not_called()


@pytest.mark.asyncio
async def test_offer_skip_removes_keyboard_when_message_id_present():
    """Skip removes inline keyboard from original message."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(f"offer_skip:{order_id}"), deps)
    deps["messenger_client"].edit_reply_markup.assert_called()


@pytest.mark.asyncio
async def test_offer_skip_no_message_id_skips_edit():
    """Skip with no message_id skips edit_reply_markup."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(
        _incoming_cb(f"offer_skip:{order_id}", message_id=None), deps
    )
    deps["messenger_client"].edit_reply_markup.assert_not_called()


# ── orr_cancel ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_price_entry_clears_state():
    """Cancel price entry clears FSM state."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(f"orr_cancel:{order_id}"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_cancel_price_entry_records_skip_when_user_and_order_known():
    """Cancel records skip for valid user and valid order_id."""
    order_id = uuid4()
    user = _user()
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(f"orr_cancel:{order_id}"), deps)
    deps["offer_dispatch_service"].record_skip.assert_called_once_with(
        order_id, user.user_id
    )


@pytest.mark.asyncio
async def test_cancel_price_entry_no_skip_when_user_not_found():
    """Cancel does not call record_skip when user is not found."""
    order_id = uuid4()
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(f"orr_cancel:{order_id}"), deps)
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_price_entry_invalid_order_id_no_skip():
    """Cancel with invalid order UUID does not call record_skip."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb("orr_cancel:not-a-uuid"), deps)
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_price_entry_answers_callback():
    """Cancel answers callback with cancelled message."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(f"orr_cancel:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()


# ── orr (rejection reason) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejection_reason_too_few_parts_returns_early():
    """orr callback with too few parts does nothing."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb("orr:bad"), deps)
    deps["messenger_client"].answer_callback.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_reason_invalid_uuid_returns_early():
    """orr callback with invalid UUID returns early."""
    deps = _deps(user=_user())
    await router.route_callback(
        _incoming_cb("orr:not-uuid:TOO_EXPENSIVE"), deps
    )
    deps["messenger_client"].answer_callback.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_reason_invalid_reason_returns_early():
    """orr callback with unknown reason value returns early."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(
        _incoming_cb(f"orr:{order_id}:UNKNOWN_REASON"), deps
    )
    deps["messenger_client"].answer_callback.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_reason_user_not_found_returns_early():
    """orr callback when user not found does nothing after answer."""
    order_id = uuid4()
    deps = _deps(user=None)
    await router.route_callback(
        _incoming_cb(f"orr:{order_id}:{RejectionReason.NO_TIME.value}"),
        deps,
    )
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_rejection_reason_low_price_sets_state():
    """LOW_PRICE reason stores order in state and prompts for price."""
    order_id = uuid4()
    user = _user()
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(f"orr:{order_id}:{RejectionReason.LOW_PRICE.value}"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(
        STATE_WAITING_DESIRED_PRICE
    )
    deps["state_store"].update_data.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_rejection_reason_non_low_price_records_skip():
    """Non-LOW_PRICE reason records skip and sends confirmation."""
    order_id = uuid4()
    user = _user()
    deps = _deps(user=user)
    reason = RejectionReason.WRONG_FORMAT
    await router.route_callback(
        _incoming_cb(f"orr:{order_id}:{reason.value}"), deps
    )
    deps["offer_dispatch_service"].record_skip.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_rejection_reason_removes_keyboard():
    """orr callback removes inline keyboard from original message."""
    order_id = uuid4()
    deps = _deps(user=_user())
    await router.route_callback(
        _incoming_cb(f"orr:{order_id}:{RejectionReason.WRONG_FORMAT.value}"),
        deps,
    )
    deps["messenger_client"].edit_reply_markup.assert_called()


# ── STATE_WAITING_DESIRED_PRICE message handler ──────────────────────────────


@pytest.mark.asyncio
async def test_desired_price_no_order_in_state_clears():
    """Handler clears state when order_id is missing from state data."""
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={},
    )
    await router.route_message(_incoming_msg("500"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_desired_price_no_text_re_prompts():
    """Handler re-prompts for price when message has no text."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
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
    deps["messenger_client"].send_text.assert_called()
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_desired_price_bounds_none_clears_state():
    """Handler clears state and sends skip msg when order bounds not found."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("500"), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_desired_price_non_numeric_text_sends_error():
    """Non-numeric price sends invalid-price error."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("100"), Decimal("1000"))
    )
    await router.route_message(_incoming_msg("abc"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_desired_price_too_low_sends_error():
    """Price at or below offer price sends invalid-price error."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("200"), Decimal("1000"))
    )
    await router.route_message(_incoming_msg("150"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_desired_price_too_high_sends_error():
    """Price above max_price sends invalid-price error."""
    order_id = uuid4()
    deps = _deps(
        user=_user(),
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("200"), Decimal("1000"))
    )
    await router.route_message(_incoming_msg("2000"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["offer_dispatch_service"].record_skip.assert_not_called()


@pytest.mark.asyncio
async def test_desired_price_user_not_found_clears_state():
    """Handler clears state when user not found during price submission."""
    order_id = uuid4()
    deps = _deps(
        user=None,
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("100"), Decimal("1000"))
    )
    await router.route_message(_incoming_msg("500"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_desired_price_valid_records_skip_and_clears():
    """Valid price records skip with LOW_PRICE reason and clears state."""
    order_id = uuid4()
    user = _user()
    deps = _deps(
        user=user,
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    result = MagicMock()
    result.manager_id = None
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("100"), Decimal("1000"))
    )
    deps["offer_dispatch_service"].record_skip = AsyncMock(return_value=result)
    await router.route_message(_incoming_msg("500"), deps)
    deps["offer_dispatch_service"].record_skip.assert_called_once()
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_desired_price_valid_notifies_manager_when_set():
    """Valid price notifies manager when result.manager_id is set."""
    order_id = uuid4()
    user = _user()
    manager_id = uuid4()
    deps = _deps(
        user=user,
        state=STATE_WAITING_DESIRED_PRICE,
        state_data={"order_id": str(order_id)},
    )
    result = MagicMock()
    result.manager_id = manager_id
    deps["offer_dispatch_service"].get_order_price_bounds = AsyncMock(
        return_value=(Decimal("100"), Decimal("1000"))
    )
    deps["offer_dispatch_service"].record_skip = AsyncMock(return_value=result)
    deps["user_role_service"].get_user_by_id = AsyncMock(return_value=None)
    await router.route_message(_incoming_msg("500"), deps)
    # Manager notification path was triggered (get_user_by_id called)
    deps["user_role_service"].get_user_by_id.assert_called()


# ── offer: (accept) ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_offer_response_user_not_found_answers_callback():
    """Offer accept with no user answers callback with denial."""
    order_id = uuid4()
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_offer_response_blocked_user_denied():
    """Blocked user gets denied answer."""
    order_id = uuid4()
    deps = _deps(user=_user(status=UserStatus.BLOCKED))
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["offer_response_service"].respond_and_finalize.assert_not_called()


@pytest.mark.asyncio
async def test_offer_response_paused_user_denied():
    """Paused user gets denied answer."""
    order_id = uuid4()
    deps = _deps(user=_user(status=UserStatus.PAUSE))
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["offer_response_service"].respond_and_finalize.assert_not_called()


@pytest.mark.asyncio
async def test_offer_response_no_blogger_profile_denied():
    """User without blogger profile gets denied."""
    order_id = uuid4()
    deps = _deps(user=_user(), blogger_profile=None)
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["offer_response_service"].respond_and_finalize.assert_not_called()


@pytest.mark.asyncio
async def test_offer_response_unconfirmed_profile_denied():
    """User with unconfirmed instagram profile gets denied."""
    order_id = uuid4()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=_user(), blogger_profile=profile)
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["offer_response_service"].respond_and_finalize.assert_not_called()


@pytest.mark.asyncio
async def test_offer_response_invalid_order_id_answers_error():
    """Offer accept with invalid UUID answers error callback."""
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=_user(), blogger_profile=profile)
    await router.route_callback(_incoming_cb("offer:not-a-uuid"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_offer_response_order_creation_error_sends_closed():
    """OrderCreationError sends order-closed message."""
    order_id = uuid4()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=_user(), blogger_profile=profile)
    deps["offer_response_service"].respond_and_finalize = AsyncMock(
        side_effect=OrderCreationError("closed")
    )
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    # answer_callback is invoked as part of order-closed handling
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_offer_response_accepted_sends_what_next():
    """Accepted offer sends what-next message and product link."""
    order_id = uuid4()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=_user(), blogger_profile=profile)

    result = MagicMock()
    result.accepted = True
    result.manager_id = None
    result.response_count = 1
    result.order = MagicMock()
    result.order.product_link = "https://shop.example.com/product"
    deps["offer_response_service"].respond_and_finalize = AsyncMock(
        return_value=result
    )
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_offer_response_not_accepted_sends_waitlist():
    """Non-accepted offer (order full) sends waitlist message."""
    order_id = uuid4()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=_user(), blogger_profile=profile)

    result = MagicMock()
    result.accepted = False
    result.manager_id = None
    deps["offer_response_service"].respond_and_finalize = AsyncMock(
        return_value=result
    )
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_offer_response_rate_limit_denies():
    """Rate-limited user gets denied."""
    order_id = uuid4()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=_user(), blogger_profile=profile)
    limiter = AsyncMock()
    limiter.allow_async = AsyncMock(return_value=False)
    deps["offer_response_rate_limiter"] = limiter
    await router.route_callback(_incoming_cb(f"offer:{order_id}"), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["offer_response_service"].respond_and_finalize.assert_not_called()
