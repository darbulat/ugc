"""Tests for Max my_orders handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.bot.max.handlers.my_orders import _strip_pay_buttons, router
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_MENU_MY_ORDERS,
    PAY_ORDER_CALLBACK_PREFIX,
)
from ugc_bot.domain.enums import MessengerType, UserStatus

# ── _strip_pay_buttons ────────────────────────────────────────────────────────


def test_strip_pay_buttons_removes_pay():
    """Pay buttons should be removed from keyboard."""
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(text="View", callback_data="view:123"),
                Button(
                    text="Pay",
                    callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}123",
                ),
            ],
            [
                Button(
                    text="Pay Only",
                    callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}456",
                ),
            ],
        ],
    )
    result = _strip_pay_buttons(kb)
    assert len(result.rows) == 1
    assert len(result.rows[0]) == 1
    assert result.rows[0][0].text == "View"


def test_strip_pay_buttons_no_pay_unchanged():
    """Keyboard without pay buttons should remain unchanged."""
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="OK", callback_data="ok")]],
    )
    result = _strip_pay_buttons(kb)
    assert len(result.rows) == 1
    assert result.rows[0][0].text == "OK"


def test_strip_pay_buttons_all_pay_returns_none():
    """An all-pay keyboard should be omitted entirely on Max."""
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="Pay",
                    callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}111",
                ),
            ],
        ],
    )
    result = _strip_pay_buttons(kb)
    assert result is None


def test_strip_pay_buttons_preserves_non_pay_in_mixed_row():
    """Only pay buttons removed; non-pay buttons in same row preserved."""
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(text="A", callback_data="a:1"),
                Button(
                    text="Pay", callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}1"
                ),
                Button(text="B", callback_data="b:2"),
            ]
        ],
    )
    result = _strip_pay_buttons(kb)
    assert len(result.rows) == 1
    texts = [btn.text for btn in result.rows[0]]
    assert "A" in texts
    assert "B" in texts
    assert "Pay" not in texts


def test_strip_pay_buttons_button_without_callback_data():
    """Buttons without callback_data are kept untouched."""
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="URL btn", callback_data=None)]],
    )
    result = _strip_pay_buttons(kb)
    assert len(result.rows) == 1


# ── helpers ───────────────────────────────────────────────────────────────────


def _user(*, status=UserStatus.ACTIVE, user_id=None):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.status = status
    u.username = "alice"
    u.country = "RU"
    return u


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


def _deps(user=None, *, advertiser=None, blogger=None):
    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    profile_service = AsyncMock()
    profile_service.get_advertiser_profile = AsyncMock(return_value=advertiser)
    profile_service.get_blogger_profile = AsyncMock(return_value=blogger)

    mock_config = MagicMock()
    mock_config.market.currency_symbol = "₽"
    mock_config.market.default_locale = "ru"
    mock_config.market.agreements_url = "https://example.com"
    mock_config.market.offer_url = "https://example.com/offer"
    mock_config.market.privacy_url = "https://example.com/privacy"
    mock_config.market.consent_url = "https://example.com/consent"
    mock_config.market.offer_url_by_country = {}
    mock_config.market.privacy_url_by_country = {}
    mock_config.market.consent_url_by_country = {}
    mock_config.docs.get_urls_for_country = MagicMock(
        return_value=(
            "https://example.com/offer",
            "https://example.com/privacy",
            "https://example.com/consent",
        )
    )

    _texts = {
        "btn_confirm_agreement": "Confirm",
    }

    async def _get_many(keys, locale="ru"):
        return {k: _texts.get(k, "") for k in keys}

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value=""),
            get_many=AsyncMock(side_effect=_get_many),
        ),
        "order_service": AsyncMock(
            list_by_advertiser=AsyncMock(return_value=[]),
        ),
        "offer_response_service": AsyncMock(
            list_by_blogger=AsyncMock(return_value=[]),
            list_by_order=AsyncMock(return_value=[]),
        ),
        "profile_service": profile_service,
        "state_store": AsyncMock(),
        "config": mock_config,
        "country_repo": None,
        "locale": "ru",
    }


# ── /my_orders command ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_my_orders_command_user_not_found():
    """/my_orders with no user sends not-found message."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_blocked_user():
    """/my_orders with blocked user sends blocked message."""
    deps = _deps(user=_user(status=UserStatus.BLOCKED))
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_pause_user():
    """/my_orders with paused user sends pause message."""
    deps = _deps(user=_user(status=UserStatus.PAUSE))
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_no_profiles_sends_fill_message():
    """/my_orders with no profiles sends fill-profile message."""
    deps = _deps(user=_user(), advertiser=None, blogger=None)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_agreement_not_confirmed_shows_prompt():
    """/my_orders when agreement not confirmed shows agreement prompt."""
    advertiser = MagicMock()
    advertiser.agreement_confirmed_at = None
    deps = _deps(user=_user(), advertiser=advertiser)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()
    # State should be set for agreement flow
    deps["state_store"].set_state.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_advertiser_no_orders():
    """/my_orders for advertiser with no orders sends no-orders message."""
    advertiser = MagicMock()
    advertiser.agreement_confirmed_at = MagicMock()
    deps = _deps(user=_user(), advertiser=advertiser)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_orders_command_blogger_no_orders():
    """/my_orders for blogger with no orders sends no-orders message."""
    blogger = MagicMock()
    blogger.agreement_confirmed_at = MagicMock()
    deps = _deps(user=_user(), blogger=blogger)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["messenger_client"].send_text.assert_called()


# ── profile menu callback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_my_orders_from_profile_callback_answers_callback():
    """CALLBACK_PROFILE_MENU_MY_ORDERS answers callback first."""
    deps = _deps(user=_user(status=UserStatus.ACTIVE))
    # No profiles → fill message path
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_MENU_MY_ORDERS), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_my_orders_from_profile_callback_user_not_found():
    """Profile menu callback with no user sends not-found."""
    deps = _deps(user=None)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_MENU_MY_ORDERS), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_my_orders_from_profile_callback_blocked_user():
    """Profile menu callback with blocked user sends blocked message."""
    deps = _deps(user=_user(status=UserStatus.BLOCKED))
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_MENU_MY_ORDERS), deps
    )
    deps["messenger_client"].answer_callback.assert_called()


# ── paginate_orders callback ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paginate_orders_advertiser_user_not_found():
    """my_orders pagination with no user answers callback error."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb("my_orders:2"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_advertiser_no_profile_answers_error():
    """my_orders pagination when advertiser profile missing answers error."""
    deps = _deps(user=_user(), advertiser=None)
    await router.route_callback(_incoming_cb("my_orders:2"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_advertiser_with_profile_calls_edit():
    """my_orders pagination with valid advertiser edits the message."""
    advertiser = MagicMock()
    advertiser.agreement_confirmed_at = MagicMock()
    deps = _deps(user=_user(), advertiser=advertiser)
    await router.route_callback(_incoming_cb("my_orders:1"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_blogger_no_profile_answers_error():
    """my_orders_blogger pagination: missing blogger profile answers error."""
    deps = _deps(user=_user(), blogger=None)
    await router.route_callback(_incoming_cb("my_orders_blogger:1"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_blogger_with_profile_answers():
    """my_orders_blogger pagination with valid blogger answers callback."""
    blogger = MagicMock()
    blogger.agreement_confirmed_at = MagicMock()
    deps = _deps(user=_user(), blogger=blogger)
    await router.route_callback(_incoming_cb("my_orders_blogger:1"), deps)
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_invalid_page_uses_page_1():
    """Pagination with non-integer page defaults to page 1."""
    advertiser = MagicMock()
    advertiser.agreement_confirmed_at = MagicMock()
    deps = _deps(user=_user(), advertiser=advertiser)
    await router.route_callback(_incoming_cb("my_orders:abc"), deps)
    deps["messenger_client"].answer_callback.assert_called()


# ── advertiser orders with existing orders ──────────────────────────────────


@pytest.mark.asyncio
async def test_my_orders_advertiser_with_orders_strips_pay_buttons():
    """Advertiser with orders: rendered page has pay buttons stripped."""
    from datetime import datetime, timezone

    order = MagicMock()
    order.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    order.order_id = uuid4()
    order.title = "Test Order"
    order.status = MagicMock(value="active")
    order.price = 1000
    order.currency_code = "RUB"
    order.bloggers_needed = 1
    order.cooperation_format = "payment"

    advertiser = MagicMock()
    advertiser.agreement_confirmed_at = MagicMock()

    user = _user()
    deps = _deps(user=user, advertiser=advertiser)
    deps["order_service"].list_by_advertiser = AsyncMock(return_value=[order])

    # _render_page returns (text, keyboard)
    pay_kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [Button(text="Details", callback_data="details:1")],
            [
                Button(
                    text="Pay",
                    callback_data=f"{PAY_ORDER_CALLBACK_PREFIX}{order.order_id}",
                ),
            ],
        ],
    )
    import ugc_bot.bot.max.handlers.my_orders as my_orders_mod

    original_render = my_orders_mod._render_page
    my_orders_mod._render_page = AsyncMock(return_value=("Orders list", pay_kb))
    try:
        await router.route_message(_incoming_msg("/my_orders"), deps)
        call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
        # Pay button should be stripped
        kb = call_kwargs.get("keyboard")
        if kb:
            for row in kb.rows:
                for btn in row:
                    assert not (
                        btn.callback_data
                        and btn.callback_data.startswith(
                            PAY_ORDER_CALLBACK_PREFIX
                        )
                    )
    finally:
        my_orders_mod._render_page = original_render


@pytest.mark.asyncio
async def test_my_orders_blogger_with_responses_shows_orders():
    """Blogger with active responses sees their orders."""
    from datetime import datetime, timezone

    resp = MagicMock()
    resp.order_id = uuid4()
    resp.blogger_id = uuid4()
    resp.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    resp.updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

    order = MagicMock()
    order.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    order.order_id = resp.order_id

    blogger = MagicMock()
    blogger.agreement_confirmed_at = MagicMock()

    user = _user()
    deps = _deps(user=user, blogger=blogger)
    deps["offer_response_service"].list_by_blogger = AsyncMock(
        return_value=[resp]
    )
    deps["order_service"].get_order = AsyncMock(return_value=order)

    import ugc_bot.bot.max.handlers.my_orders as my_orders_mod

    original_render = my_orders_mod._render_blogger_orders_page
    my_orders_mod._render_blogger_orders_page = MagicMock(
        return_value=(
            "Blogger orders",
            Keyboard(kind=KeyboardKind.INLINE, rows=[]),
        )
    )
    try:
        await router.route_message(_incoming_msg("/my_orders"), deps)
        deps["messenger_client"].send_text.assert_called()
    finally:
        my_orders_mod._render_blogger_orders_page = original_render


@pytest.mark.asyncio
async def test_my_orders_blogger_agreement_not_confirmed():
    """Blogger with unconfirmed agreement sees agreement prompt."""
    blogger = MagicMock()
    blogger.agreement_confirmed_at = None

    deps = _deps(user=_user(), blogger=blogger)
    await router.route_message(_incoming_msg("/my_orders"), deps)
    deps["state_store"].set_state.assert_called()


@pytest.mark.asyncio
async def test_paginate_orders_blogger_with_responses():
    """my_orders_blogger pagination with valid responses edits message."""
    from datetime import datetime, timezone

    resp = MagicMock()
    resp.order_id = uuid4()
    resp.blogger_id = uuid4()
    resp.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    resp.updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

    order = MagicMock()
    order.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    order.order_id = resp.order_id

    blogger = MagicMock()
    blogger.agreement_confirmed_at = MagicMock()

    deps = _deps(user=_user(), blogger=blogger)
    deps["offer_response_service"].list_by_blogger = AsyncMock(
        return_value=[resp]
    )
    deps["order_service"].get_order = AsyncMock(return_value=order)

    import ugc_bot.bot.max.handlers.my_orders as my_orders_mod

    original_render = my_orders_mod._render_blogger_orders_page
    my_orders_mod._render_blogger_orders_page = MagicMock(
        return_value=(
            "Blogger orders page 2",
            Keyboard(kind=KeyboardKind.INLINE, rows=[]),
        )
    )
    try:
        await router.route_callback(_incoming_cb("my_orders_blogger:2"), deps)
        deps["messenger_client"].edit_text.assert_called()
    finally:
        my_orders_mod._render_blogger_orders_page = original_render
