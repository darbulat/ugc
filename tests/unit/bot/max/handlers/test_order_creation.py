"""Tests for Max order creation handlers."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.order_creation import (
    _content_usage_from_callback,
    _deadlines_label_from_callback,
    _deadlines_offer_from_callback,
    _parse_bloggers_callback_data,
    handle_content_usage_callback,
    handle_cooperation_format_callback,
    handle_order_type_callback,
    router,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ORDER_AGREE,
    CALLBACK_PROFILE_MENU_CREATE_ORDER,
)
from ugc_bot.bot.telegram.handlers.order_creation_states import (
    CALLBACK_ORDER_BLOGGERS_PREFIX,
    CALLBACK_ORDER_CONTENT_ADS,
    CALLBACK_ORDER_CONTENT_BOTH,
    CALLBACK_ORDER_CONTENT_SOCIAL,
    CALLBACK_ORDER_COOP_BARTER,
    CALLBACK_ORDER_COOP_BOTH,
    CALLBACK_ORDER_COOP_PAYMENT,
    CALLBACK_ORDER_DEADLINES_PREFIX,
    CALLBACK_ORDER_TYPE_PLACEMENT,
    CALLBACK_ORDER_TYPE_UGC,
    COOP_BARTER,
    COOP_BOTH,
    COOP_PAYMENT,
    DEADLINES_3,
    DEADLINES_7,
    DEADLINES_14,
    OrderCreationStates,
)
from ugc_bot.bot.telegram.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.domain.enums import MessengerType, OrderType, UserStatus

# FSM state constants
_STATE_ORDER_TYPE = OrderCreationStates.order_type.state
_STATE_OFFER_TEXT = OrderCreationStates.offer_text.state
_STATE_COOPERATION = OrderCreationStates.cooperation_format.state
_STATE_PRICE = OrderCreationStates.price.state
_STATE_BARTER = OrderCreationStates.barter_description.state
_STATE_BLOGGERS = OrderCreationStates.bloggers_needed.state
_STATE_PRODUCT_LINK = OrderCreationStates.product_link.state
_STATE_CONTENT_USAGE = OrderCreationStates.content_usage.state
_STATE_DEADLINES = OrderCreationStates.deadlines.state
_STATE_GEOGRAPHY = OrderCreationStates.geography.state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(*, status=UserStatus.ACTIVE, username="alice"):
    u = MagicMock()
    u.user_id = uuid4()
    u.status = status
    u.username = username
    u.country = "RU"
    u.language = "ru"
    return u


def _advertiser(*, agreement_confirmed_at="2024-01-01"):
    a = MagicMock()
    a.agreement_confirmed_at = agreement_confirmed_at
    return a


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


def _deps(user=None, advertiser=None):
    mock_config = MagicMock()
    mock_config.market.default_locale = "ru"
    mock_config.market.currency_symbol = "₽"
    mock_config.market.max_order_price = 1_000_000.0
    mock_config.market.agreements_url = "https://example.com"
    mock_config.market.privacy_url = "https://example.com"
    mock_config.market.consent_url = "https://example.com"
    mock_config.market.offer_url = "https://example.com"
    mock_config.market.offer_url_by_country = {}
    mock_config.market.privacy_url_by_country = {}
    mock_config.market.consent_url_by_country = {}
    mock_config.admin.admin_base_url = "https://admin.example.com"
    mock_config.referral.referral_support_chat_id = ""
    # format_agreements_message calls config.docs.get_urls_for_country
    mock_config.docs.get_urls_for_country.return_value = (
        "https://offer.example.com",
        "https://privacy.example.com",
        "https://consent.example.com",
    )

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)
    user_role_service.get_user_by_id = AsyncMock(return_value=user)

    if advertiser is None:
        advertiser = _advertiser()

    profile_service = AsyncMock()
    profile_service.get_advertiser_profile = AsyncMock(return_value=advertiser)

    state_store = AsyncMock()
    state_store.get_data = AsyncMock(return_value={})
    state_store.get_state = AsyncMock(return_value=None)

    return {
        "messenger_client": AsyncMock(),
        "telegram_messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "profile_service": profile_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value="some text"),
            get_many=AsyncMock(return_value={}),
        ),
        "state_store": state_store,
        "config": mock_config,
        "order_service": AsyncMock(),
        "advertiser_registration_service": AsyncMock(),
        "content_moderation_service": AsyncMock(),
        "country_repo": AsyncMock(),
        "locale": "ru",
    }


def _full_order_state_data(user_id, cooperation_format=COOP_PAYMENT):
    """Return state data dict populated for the geography step."""
    return {
        "user_id": str(user_id),
        "order_type": OrderType.UGC_ONLY.value,
        "offer_text": "Make a great video",
        "cooperation_format": cooperation_format,
        "price": 5000.0,
        "barter_description": None,
        "bloggers_needed": 3,
        "product_link": "https://example.com/product",
        "content_usage": "social",
        "deadlines": "3 days",
    }


# ---------------------------------------------------------------------------
# Pure helper function tests
# ---------------------------------------------------------------------------


def test_parse_bloggers_callback_data_valid():
    assert _parse_bloggers_callback_data("order:bloggers:5") == 5


def test_parse_bloggers_callback_data_invalid_number():
    assert _parse_bloggers_callback_data("order:bloggers:abc") is None


def test_parse_bloggers_callback_data_wrong_prefix():
    assert _parse_bloggers_callback_data("order:type:ugc") is None


def test_parse_bloggers_callback_data_empty():
    assert _parse_bloggers_callback_data("") is None


def test_deadlines_label_from_callback_3():
    assert (
        _deadlines_label_from_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}3")
        == DEADLINES_3
    )


def test_deadlines_label_from_callback_7():
    assert (
        _deadlines_label_from_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}7")
        == DEADLINES_7
    )


def test_deadlines_label_from_callback_14():
    assert (
        _deadlines_label_from_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}14")
        == DEADLINES_14
    )


def test_deadlines_label_from_callback_unknown():
    assert (
        _deadlines_label_from_callback(f"{CALLBACK_ORDER_DEADLINES_PREFIX}99")
        is None
    )


def test_deadlines_label_from_callback_wrong_prefix():
    assert _deadlines_label_from_callback("order:type:ugc") is None


def test_deadlines_label_from_callback_empty():
    assert _deadlines_label_from_callback("") is None


def test_deadlines_offer_from_callback_3():
    result = _deadlines_offer_from_callback(
        f"{CALLBACK_ORDER_DEADLINES_PREFIX}3"
    )
    assert result is not None


def test_deadlines_offer_from_callback_none_for_unknown():
    assert _deadlines_offer_from_callback("bad") is None


def test_content_usage_from_callback_social():
    result = _content_usage_from_callback(CALLBACK_ORDER_CONTENT_SOCIAL)
    assert result is not None


def test_content_usage_from_callback_ads():
    result = _content_usage_from_callback(CALLBACK_ORDER_CONTENT_ADS)
    assert result is not None


def test_content_usage_from_callback_both():
    result = _content_usage_from_callback(CALLBACK_ORDER_CONTENT_BOTH)
    assert result is not None


def test_content_usage_from_callback_unknown():
    assert _content_usage_from_callback("order:content:unknown") is None


# ---------------------------------------------------------------------------
# /create_order command — _start_order_flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_command_happy_path_sets_state():
    """/create_order with full advertiser profile sets ORDER_TYPE state."""
    user = _user()
    deps = _deps(user)
    await router.route_message(_incoming_msg("/create_order"), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_ORDER_TYPE)


@pytest.mark.asyncio
async def test_create_order_command_user_not_found():
    """Missing user gets a text response and state is never set."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/create_order"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_create_order_command_blocked_user():
    """Blocked user gets a text response and state is never set."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user)
    await router.route_message(_incoming_msg("/create_order"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_create_order_no_advertiser_profile():
    """User without advertiser profile gets fill-profile message."""
    user = _user()
    deps = _deps(user, advertiser=None)
    deps["profile_service"].get_advertiser_profile = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("/create_order"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_create_order_agreement_not_confirmed_sets_agreements_state():
    """Advertiser with no agreement confirmation is shown agreement keyboard."""
    user = _user()
    deps = _deps(user, advertiser=_advertiser(agreement_confirmed_at=None))
    # confirm_agreement_inline_keyboard requires btn_confirm_agreement in texts
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"btn_confirm_agreement": "I agree"}
    )
    await router.route_message(_incoming_msg("/create_order"), deps)
    deps["state_store"].set_state.assert_called_with(
        _ADVERTISER_AGREEMENTS_STATE
    )
    deps["messenger_client"].send_text.assert_called()
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_MENU_CREATE_ORDER
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_order_profile_callback_happy_path():
    """Profile menu create-order callback answers callback and sets state."""
    user = _user()
    deps = _deps(user)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_MENU_CREATE_ORDER), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["state_store"].set_state.assert_called_once_with(_STATE_ORDER_TYPE)


@pytest.mark.asyncio
async def test_create_order_profile_callback_user_not_found():
    """Profile callback with no user answers callback and sends text."""
    deps = _deps(user=None)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_MENU_CREATE_ORDER), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# CALLBACK_ORDER_AGREE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_agree_callback_wrong_state_returns_early():
    """Agree callback in wrong state just answers callback without action."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value="some_other_state")
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_AGREE), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_order_agree_callback_wrong_flow_type():
    """Agree callback with non-order_creation flow_type returns early."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_ADVERTISER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"flow_type": "advertiser_registration"}
    )
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_AGREE), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_order_agree_callback_missing_user_id_sends_expired():
    """Agree callback with no user_id in state clears
    state and sends expired message."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_ADVERTISER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"flow_type": "order_creation"}  # no user_id
    )
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_AGREE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called_once()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_order_agree_callback_happy_path():
    """Agree callback confirms agreement and sets ORDER_TYPE state."""
    user_id = uuid4()
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_ADVERTISER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"flow_type": "order_creation", "user_id": str(user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_AGREE), deps)
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_called_once_with(user_id=user_id)
    deps["state_store"].set_state.assert_called_once_with(_STATE_ORDER_TYPE)
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# Order type callback handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_type_ugc_callback_sets_offer_text_state():
    """UGC order type callback stores order type and sets OFFER_TEXT state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_ORDER_TYPE)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_TYPE_UGC), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(_STATE_OFFER_TEXT)


@pytest.mark.asyncio
async def test_order_type_placement_callback_sets_offer_text_state():
    """Placement order type callback stores order type
    and sets OFFER_TEXT state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_ORDER_TYPE)
    await router.route_callback(
        _incoming_cb(CALLBACK_ORDER_TYPE_PLACEMENT), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_OFFER_TEXT)


# ---------------------------------------------------------------------------
# Order type text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_type_text_ugc_only_advances_state():
    """Valid UGC-only text advances to OFFER_TEXT state."""
    from ugc_bot.bot.telegram.handlers.order_creation_states import (
        ORDER_TYPE_UGC_ONLY,
    )

    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_ORDER_TYPE)
    await router.route_message(_incoming_msg(ORDER_TYPE_UGC_ONLY), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_OFFER_TEXT)


@pytest.mark.asyncio
async def test_order_type_text_ugc_plus_placement_advances_state():
    """Valid UGC+placement text advances to OFFER_TEXT state."""
    from ugc_bot.bot.telegram.handlers.order_creation_states import (
        ORDER_TYPE_UGC_PLUS_PLACEMENT,
    )

    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_ORDER_TYPE)
    await router.route_message(
        _incoming_msg(ORDER_TYPE_UGC_PLUS_PLACEMENT), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_OFFER_TEXT)


@pytest.mark.asyncio
async def test_order_type_text_invalid_shows_keyboard():
    """Invalid text re-shows order type keyboard without advancing state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_ORDER_TYPE)
    await router.route_message(_incoming_msg("gibberish"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Offer text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offer_text_valid_advances_to_cooperation():
    """Valid offer text advances to COOPERATION state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_OFFER_TEXT)
    # Long enough to pass validate_offer_text (typically ≥10 chars)
    await router.route_message(_incoming_msg("A" * 30), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_COOPERATION)


@pytest.mark.asyncio
async def test_offer_text_too_short_sends_error():
    """Offer text that is too short sends error message without advancing."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_OFFER_TEXT)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_offer_text_too_short": "Too short"}
    )
    await router.route_message(_incoming_msg("hi"), deps)
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Cooperation format callback handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coop_payment_callback_sets_price_state():
    """Payment cooperation callback sets PRICE state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_COOP_PAYMENT), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRICE)


@pytest.mark.asyncio
async def test_coop_barter_callback_sets_barter_state():
    """Barter cooperation callback sets BARTER state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_COOP_BARTER), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BARTER)


@pytest.mark.asyncio
async def test_coop_both_callback_sets_price_state_first():
    """Both cooperation callback sets PRICE state (price before barter)."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_COOP_BOTH), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRICE)


# ---------------------------------------------------------------------------
# Cooperation format text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coop_format_text_payment_sets_price_state():
    """Payment text cooperation sets PRICE state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_message(_incoming_msg(COOP_PAYMENT), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRICE)


@pytest.mark.asyncio
async def test_coop_format_text_barter_sets_barter_state():
    """Barter text cooperation sets BARTER state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_message(_incoming_msg(COOP_BARTER), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BARTER)


@pytest.mark.asyncio
async def test_coop_format_text_both_sets_price_state():
    """Both text cooperation sets PRICE state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_message(_incoming_msg(COOP_BOTH), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRICE)


@pytest.mark.asyncio
async def test_coop_format_text_invalid_shows_keyboard():
    """Invalid cooperation text re-shows keyboard without advancing state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_COOPERATION)
    await router.route_message(_incoming_msg("not a valid format"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Price handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_non_numeric_sends_error():
    """Non-numeric price input sends error without advancing state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRICE)
    await router.route_message(_incoming_msg("not a number"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_price_too_high_sends_error():
    """Price exceeding max sends error without advancing state."""
    deps = _deps()
    deps["config"].market.max_order_price = 1_000.0
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_price_too_high": "Price too high"}
    )
    await router.route_message(_incoming_msg("999999"), deps)
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_price_valid_payment_sets_bloggers_state():
    """Valid price for PAYMENT cooperation sets BLOGGERS state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRICE)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_PAYMENT}
    )
    await router.route_message(_incoming_msg("5000"), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BLOGGERS)


@pytest.mark.asyncio
async def test_price_valid_coop_both_sets_barter_state():
    """Valid price for BOTH cooperation sets BARTER state next."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRICE)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_BOTH}
    )
    await router.route_message(_incoming_msg("3000"), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BARTER)


@pytest.mark.asyncio
async def test_price_with_comma_is_accepted():
    """Price with comma as decimal separator is accepted."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRICE)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_PAYMENT}
    )
    await router.route_message(_incoming_msg("1,500"), deps)
    # 1.5 as price is valid — state should advance
    deps["state_store"].set_state.assert_called_once_with(_STATE_BLOGGERS)


# ---------------------------------------------------------------------------
# Barter description handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_barter_description_valid_sets_bloggers_state():
    """Valid barter description advances to BLOGGERS state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BARTER)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_BARTER}
    )
    await router.route_message(_incoming_msg("B" * 30), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BLOGGERS)


@pytest.mark.asyncio
async def test_barter_description_empty_when_coop_barter_advances():
    """Empty barter description for pure-barter coop
    is optional and advances state.

    required = (coop == COOP_BOTH),
    so COOP_BARTER gives required=False.
    """
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BARTER)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_BARTER}
    )
    await router.route_message(_incoming_msg(""), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_BLOGGERS)


@pytest.mark.asyncio
async def test_barter_description_empty_when_coop_both_sends_error():
    """Empty barter description for BOTH cooperation
    is required and sends error.

    required = (coop == COOP_BOTH),
    so COOP_BOTH gives required=True.
    """
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BARTER)
    deps["state_store"].get_data = AsyncMock(
        return_value={"cooperation_format": COOP_BOTH}
    )
    await router.route_message(_incoming_msg(""), deps)
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Bloggers needed callback handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bloggers_needed_callback_valid_sets_product_link_state():
    """Valid bloggers callback sets PRODUCT_LINK state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BLOGGERS)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}3"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRODUCT_LINK)


@pytest.mark.asyncio
async def test_bloggers_needed_callback_invalid_count_answers_only():
    """Bloggers callback with count not in allowed set just answers callback."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BLOGGERS)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}99"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_bloggers_needed_callback_non_numeric_answers_only():
    """Bloggers callback with non-numeric suffix just answers callback."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BLOGGERS)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_BLOGGERS_PREFIX}abc"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Bloggers needed text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bloggers_needed_text_valid_advances_state():
    """Valid bloggers count text advances to PRODUCT_LINK state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BLOGGERS)
    await router.route_message(_incoming_msg("3"), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_PRODUCT_LINK)


@pytest.mark.asyncio
async def test_bloggers_needed_text_invalid_shows_keyboard():
    """Invalid bloggers count text re-shows keyboard."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_BLOGGERS)
    deps["bot_texts_service"].get = AsyncMock(return_value="Choose {counts}")
    await router.route_message(_incoming_msg("7"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Product link handler (Max: photo=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_link_valid_sets_content_usage_state():
    """Valid product URL advances to CONTENT_USAGE
    state and stores None as photo."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRODUCT_LINK)
    await router.route_message(
        _incoming_msg("https://example.com/product"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_CONTENT_USAGE)
    # Verify photo is explicitly None (Max-specific: no photo upload)
    call_kwargs_list = deps["state_store"].update_data.call_args_list
    update_calls_with_photo = [
        c for c in call_kwargs_list if "product_photo_file_id" in c.kwargs
    ]
    assert any(
        c.kwargs["product_photo_file_id"] is None
        for c in update_calls_with_photo
    )


@pytest.mark.asyncio
async def test_product_link_invalid_sends_error():
    """Invalid product link sends error without advancing."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_PRODUCT_LINK)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_product_link_invalid": "Invalid URL"}
    )
    await router.route_message(_incoming_msg("not-a-url"), deps)
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Content usage callback handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_usage_social_callback_sets_deadlines_state():
    """Social content usage callback sets DEADLINES state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_callback(
        _incoming_cb(CALLBACK_ORDER_CONTENT_SOCIAL), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


@pytest.mark.asyncio
async def test_content_usage_ads_callback_sets_deadlines_state():
    """Ads content usage callback sets DEADLINES state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_CONTENT_ADS), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


@pytest.mark.asyncio
async def test_content_usage_both_callback_sets_deadlines_state():
    """Both content usage callback sets DEADLINES state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_callback(_incoming_cb(CALLBACK_ORDER_CONTENT_BOTH), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


# ---------------------------------------------------------------------------
# Content usage text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_usage_text_valid_social_advances():
    """Valid social content usage text advances to DEADLINES state."""
    from ugc_bot.bot.telegram.handlers.order_creation_states import (
        CONTENT_USAGE_SOCIAL,
    )

    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_message(_incoming_msg(CONTENT_USAGE_SOCIAL), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


@pytest.mark.asyncio
async def test_content_usage_text_valid_ads_advances():
    """Valid ads content usage text advances to DEADLINES state."""
    from ugc_bot.bot.telegram.handlers.order_creation_states import (
        CONTENT_USAGE_ADS,
    )

    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_message(_incoming_msg(CONTENT_USAGE_ADS), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


@pytest.mark.asyncio
async def test_content_usage_text_valid_both_advances():
    """Valid both content usage text advances to DEADLINES state."""
    from ugc_bot.bot.telegram.handlers.order_creation_states import (
        CONTENT_USAGE_BOTH,
    )

    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_message(_incoming_msg(CONTENT_USAGE_BOTH), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_DEADLINES)


@pytest.mark.asyncio
async def test_content_usage_text_invalid_shows_keyboard():
    """Invalid content usage text re-shows keyboard."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_CONTENT_USAGE)
    await router.route_message(_incoming_msg("wrong choice"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Deadlines callback handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadlines_3_callback_sets_geography_state():
    """3-day deadline callback sets GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_DEADLINES_PREFIX}3"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_7_callback_sets_geography_state():
    """7-day deadline callback sets GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_DEADLINES_PREFIX}7"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_14_callback_sets_geography_state():
    """14-day deadline callback sets GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_DEADLINES_PREFIX}14"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_unknown_callback_answers_only():
    """Unknown deadline callback just answers callback without advancing."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_ORDER_DEADLINES_PREFIX}99"), deps
    )
    deps["messenger_client"].answer_callback.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Deadlines text handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadlines_text_3_days_sets_geography_state():
    """3-days text deadline advances to GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_message(_incoming_msg(DEADLINES_3), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_text_7_days_sets_geography_state():
    """7-days text deadline advances to GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_message(_incoming_msg(DEADLINES_7), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_text_14_days_sets_geography_state():
    """14-days text deadline advances to GEOGRAPHY state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_message(_incoming_msg(DEADLINES_14), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_GEOGRAPHY)


@pytest.mark.asyncio
async def test_deadlines_text_invalid_shows_keyboard():
    """Invalid deadline text re-shows keyboard."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_DEADLINES)
    await router.route_message(_incoming_msg("tomorrow"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Geography handler — final step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geography_invalid_sends_error():
    """Invalid geography text sends error without creating order."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_geography_invalid": "Invalid"}
    )
    await router.route_message(_incoming_msg(""), deps)
    deps["order_service"].create_order.assert_not_called()


@pytest.mark.asyncio
async def test_geography_session_expired_clears_state():
    """Missing user_id in state data clears state and sends expired message."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["state_store"].get_data = AsyncMock(return_value={})  # no user_id
    await router.route_message(_incoming_msg("Moscow"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called_once()
    deps["order_service"].create_order.assert_not_called()


@pytest.mark.asyncio
async def test_geography_creates_order_and_sends_confirmation():
    """Valid geography creates order, clears state,
    sends confirmation text (no invoice)."""
    user = _user()
    user_id = user.user_id
    deps = _deps(user)
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["state_store"].get_data = AsyncMock(
        return_value=_full_order_state_data(user_id)
    )
    order_mock = MagicMock()
    deps["order_service"].create_order = AsyncMock(return_value=order_mock)

    await router.route_message(_incoming_msg("Moscow"), deps)

    deps["order_service"].create_order.assert_called_once()
    call_kwargs = deps["order_service"].create_order.call_args.kwargs
    # Max-specific: no photo
    assert call_kwargs["product_photo_file_id"] is None
    deps["state_store"].clear.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_geography_barter_coop_sets_price_to_zero():
    """For barter cooperation, price is set to 0.0 regardless of state data."""
    user = _user()
    user_id = user.user_id
    deps = _deps(user)
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["state_store"].get_data = AsyncMock(
        return_value=_full_order_state_data(
            user_id, cooperation_format=COOP_BARTER
        )
    )
    order_mock = MagicMock()
    deps["order_service"].create_order = AsyncMock(return_value=order_mock)

    await router.route_message(_incoming_msg("Moscow"), deps)

    call_kwargs = deps["order_service"].create_order.call_args.kwargs
    assert call_kwargs["price"] == 0.0


@pytest.mark.asyncio
async def test_geography_notifies_support_chat_when_configured():
    """Order creation notifies support chat
    when support_chat_id is configured."""
    user = _user()
    user_id = user.user_id
    deps = _deps(user)
    deps["config"].referral.referral_support_chat_id = "  -100123456789  "
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["state_store"].get_data = AsyncMock(
        return_value=_full_order_state_data(user_id)
    )
    order_mock = MagicMock()
    deps["order_service"].create_order = AsyncMock(return_value=order_mock)
    deps["user_role_service"].get_user_by_id = AsyncMock(return_value=user)

    with (
        patch(
            "ugc_bot.bot.max.handlers.order_creation.notify_admins_about_order_created",
            new_callable=AsyncMock,
        ) as mock_admin,
        patch(
            "ugc_bot.bot.max.handlers.order_creation.notify_support_chat_about_new_order",
            new_callable=AsyncMock,
        ) as mock_support,
    ):
        await router.route_message(_incoming_msg("Moscow"), deps)

    # Both notifications go via Telegram client, not Max client
    mock_admin.assert_called_once()
    assert (
        mock_admin.call_args.kwargs["messenger_client"]
        is deps["telegram_messenger_client"]
    )
    mock_support.assert_called_once()
    assert (
        mock_support.call_args.kwargs["messenger_client"]
        is deps["telegram_messenger_client"]
    )


@pytest.mark.asyncio
async def test_geography_skips_support_chat_when_not_configured():
    """Order creation skips support chat when support_chat_id is empty.

    notify_admins_about_order_created always calls get_user_by_id once.
    When support_chat_id is empty, notify_support_chat is skipped, so
    get_user_by_id is called exactly once (by admin notify only).
    """
    user = _user()
    user_id = user.user_id
    deps = _deps(user)
    deps["config"].referral.referral_support_chat_id = ""
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    deps["state_store"].get_data = AsyncMock(
        return_value=_full_order_state_data(user_id)
    )
    order_mock = MagicMock()
    deps["order_service"].create_order = AsyncMock(return_value=order_mock)

    await router.route_message(_incoming_msg("Moscow"), deps)

    # get_user_by_id is called once by notify_admins,
    # but NOT again for support chat
    assert deps["user_role_service"].get_user_by_id.call_count == 1


@pytest.mark.asyncio
async def test_geography_invalid_order_type_defaults_to_ugc_only():
    """Invalid order_type in state defaults to UGC_ONLY without raising."""
    user = _user()
    user_id = user.user_id
    deps = _deps(user)
    deps["state_store"].get_state = AsyncMock(return_value=_STATE_GEOGRAPHY)
    state_data = _full_order_state_data(user_id)
    state_data["order_type"] = "invalid_value"
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    order_mock = MagicMock()
    deps["order_service"].create_order = AsyncMock(return_value=order_mock)

    await router.route_message(_incoming_msg("Moscow"), deps)

    call_kwargs = deps["order_service"].create_order.call_args.kwargs
    assert call_kwargs["order_type"] == OrderType.UGC_ONLY


# ---------------------------------------------------------------------------
# Defensive guard branches — called directly to bypass predicate routing
# ---------------------------------------------------------------------------
# These defensive branches (lines 321-322, 483-484, 772-773) are only
# reachable by calling the handler function directly, because the router
# predicate already filters out mismatched data values.


@pytest.mark.asyncio
async def test_order_type_callback_handler_unknown_data_answers_only():
    """handle_order_type_callback with unknown data just answers callback."""
    deps = _deps()
    # Build a callback whose data does not match either type constant
    incoming = _incoming_cb("order:type:unknown")
    await handle_order_type_callback(incoming, deps)
    deps["messenger_client"].answer_callback.assert_called_once_with(
        callback_id="cb_1"
    )
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_cooperation_format_callback_handler_unknown_data_answers_only():
    """handle_cooperation_format_callback with unknown
    data just answers callback."""
    deps = _deps()
    incoming = _incoming_cb("order:coop:unknown")
    await handle_cooperation_format_callback(incoming, deps)
    deps["messenger_client"].answer_callback.assert_called_once_with(
        callback_id="cb_1"
    )
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_content_usage_callback_handler_unknown_data_answers_only():
    """handle_content_usage_callback with unknown data just answers callback."""
    deps = _deps()
    incoming = _incoming_cb("order:content:unknown")
    await handle_content_usage_callback(incoming, deps)
    deps["messenger_client"].answer_callback.assert_called_once_with(
        callback_id="cb_1"
    )
    deps["state_store"].set_state.assert_not_called()
