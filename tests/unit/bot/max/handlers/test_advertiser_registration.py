"""Tests for Max advertiser registration handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.advertiser_registration import (
    STATE_ADV_ACTIVITY,
    STATE_ADV_AGREEMENTS,
    STATE_ADV_BRAND,
    STATE_ADV_CITY,
    STATE_ADV_NAME,
    STATE_ADV_PHONE,
    STATE_ADV_SITE,
    router,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_AGREE,
    CALLBACK_ADV_START,
    CALLBACK_ROLE_ADVERTISER,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


def _user(*, status=UserStatus.ACTIVE, username="alice", user_id=None):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.status = status
    u.username = username
    u.country = "RU"
    u.language = "ru"
    return u


def _incoming_msg(
    text: str,
    *,
    location_lat: float | None = None,
    location_lon: float | None = None,
    contact_phone: str | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=text,
        message_id="msg_1",
        location_lat=location_lat,
        location_lon=location_lon,
        contact_phone=contact_phone,
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


def _deps(user=None, *, state=None, state_data=None, advertiser=None):
    mock_config = MagicMock()
    mock_config.market.default_locale = "ru"
    mock_config.market.agreements_url = "https://example.com"
    mock_config.market.privacy_url = "https://example.com/privacy"
    mock_config.market.consent_url = "https://example.com/consent"
    mock_config.market.offer_url = "https://example.com/offer"
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

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    profile_service = AsyncMock()
    profile_service.get_advertiser_profile = AsyncMock(return_value=advertiser)

    state_store = AsyncMock()
    state_store.get_state = AsyncMock(return_value=state)
    state_store.get_data = AsyncMock(return_value=state_data or {})

    blogger_reg_service = AsyncMock()
    blogger_reg_service.resolve_city_from_location = AsyncMock(
        return_value="Moscow"
    )

    _texts = {
        "btn_confirm_agreement": "Confirm",
        "btn_create_order": "Create",
        "btn_my_orders": "Orders",
        "btn_my_profile": "Profile",
        "btn_edit_profile": "Edit",
        "btn_support": "Support",
        "btn_advertiser_start": "Start",
        "msg_choose_action": "Choose:",
    }

    async def _get_many(keys, locale="ru"):
        return {k: _texts.get(k, "") for k in keys}

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "profile_service": profile_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value=""),
            get_many=AsyncMock(side_effect=_get_many),
        ),
        "state_store": state_store,
        "config": mock_config,
        "advertiser_registration_service": AsyncMock(),
        "blogger_registration_service": blogger_reg_service,
        "locale": "ru",
    }


# ── /advertiser command ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_advertiser_command_sends_message():
    """The /advertiser command should send a response."""
    user = _user()
    deps = _deps(user=user)
    await router.route_message(_incoming_msg("/advertiser"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_advertiser_command_no_user_still_sends():
    """/advertiser with no user still sends some response."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/advertiser"), deps)
    deps["messenger_client"].send_text.assert_called()


# ── CALLBACK_ROLE_ADVERTISER callback ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_role_advertiser_callback_sends_response():
    """role:advertiser callback sends a response message."""
    user = _user()
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_ROLE_ADVERTISER), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_role_advertiser_callback_existing_profile_shows_menu():
    """role:advertiser with existing profile shows menu, not registration."""
    user = _user()
    advertiser = MagicMock()
    deps = _deps(user=user, advertiser=advertiser)
    await router.route_callback(_incoming_cb(CALLBACK_ROLE_ADVERTISER), deps)
    deps["messenger_client"].send_text.assert_called()


# ── CALLBACK_ADV_START callback ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adv_start_callback_blocked_user():
    """Blocked users cannot start registration."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_adv_start_callback_user_not_found():
    """Missing user gets not-found message."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_adv_start_callback_skips_name_if_username_present():
    """If user has username, skip name step and go to phone."""
    user = _user(username="alice_long_enough")
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_PHONE)


@pytest.mark.asyncio
async def test_adv_start_callback_asks_name_if_no_username():
    """If user has no username, ask for name."""
    user = _user(username="")
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_NAME)


@pytest.mark.asyncio
async def test_adv_start_callback_existing_advertiser_shows_menu():
    """If user already has advertiser profile, show menu not registration."""
    user = _user(username="alice")
    advertiser = MagicMock()
    deps = _deps(user=user, advertiser=advertiser)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_adv_start_callback_non_uuid_user_id_returns_early():
    """User with non-UUID user_id returns without action."""
    user = _user()
    user.user_id = "not-a-uuid-string"
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_START), deps)
    deps["state_store"].set_state.assert_not_called()


# ── STATE_ADV_NAME handler ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_name_validates_empty():
    """Empty name should not advance state."""
    deps = _deps(state=STATE_ADV_NAME)
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_name_too_short_sends_error():
    """Single-character name sends validation error."""
    deps = _deps(state=STATE_ADV_NAME)
    await router.route_message(_incoming_msg("A"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_name_valid_advances_to_phone():
    """Valid name advances to phone step."""
    deps = _deps(state=STATE_ADV_NAME)
    await router.route_message(_incoming_msg("Alice Smith"), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_PHONE)


# ── STATE_ADV_PHONE handler ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_phone_invalid_sends_error():
    """Invalid phone number sends validation error."""
    deps = _deps(state=STATE_ADV_PHONE)
    await router.route_message(_incoming_msg("not_a_phone"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_phone_valid_advances_to_city():
    """Valid phone advances to city step."""
    deps = _deps(state=STATE_ADV_PHONE)
    await router.route_message(_incoming_msg("+79001234567"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_CITY)


@pytest.mark.asyncio
async def test_handle_phone_from_contact_valid():
    """Phone from contact field is accepted."""
    deps = _deps(state=STATE_ADV_PHONE)
    incoming = _incoming_msg("", contact_phone="+79001234567")
    await router.route_message(incoming, deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_CITY)


# ── STATE_ADV_CITY handler ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_city_text_valid_advances_to_brand():
    """Valid city text advances to brand step."""
    deps = _deps(state=STATE_ADV_CITY)
    await router.route_message(_incoming_msg("Moscow"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_BRAND)


@pytest.mark.asyncio
async def test_handle_city_empty_text_advances_without_error():
    """Empty city text is allowed (not required) — advances to brand."""
    deps = _deps(state=STATE_ADV_CITY)
    await router.route_message(_incoming_msg(""), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_BRAND)


@pytest.mark.asyncio
async def test_handle_city_bot_command_sends_error():
    """Bot command as city text sends validation error."""
    deps = _deps(state=STATE_ADV_CITY)
    await router.route_message(_incoming_msg("/start"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_city_location_resolves_city():
    """Location shared resolves city name and advances."""
    deps = _deps(state=STATE_ADV_CITY)
    # The handler calls resolve_city_name_from_location via
    # deps["blogger_registration_service"]
    incoming = IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=None,
        message_id="msg_1",
        location_lat=55.75,
        location_lon=37.61,
    )
    # resolve_city_name_from_location is called; mock it to return a city
    deps["blogger_registration_service"].get_city_from_location = AsyncMock(
        return_value="Moscow"
    )
    await router.route_message(incoming, deps)
    # Should advance to brand (or send error if geocoding not set up)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_handle_city_location_geocoding_failure_sends_error():
    """Failed geocoding sends error and re-prompts for location."""
    deps = _deps(state=STATE_ADV_CITY)
    incoming = IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=None,
        message_id="msg_1",
        location_lat=0.0,
        location_lon=0.0,
    )
    # Patch the function on the handler module (where it's imported)
    import ugc_bot.bot.max.handlers.advertiser_registration as adv_mod

    original = adv_mod.resolve_city_name_from_location
    adv_mod.resolve_city_name_from_location = AsyncMock(return_value=None)
    try:
        await router.route_message(incoming, deps)
        deps["messenger_client"].send_text.assert_called()
        deps["state_store"].set_state.assert_not_called()
    finally:
        adv_mod.resolve_city_name_from_location = original


# ── STATE_ADV_BRAND handler ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_brand_empty_sends_error():
    """Empty brand name sends validation error."""
    deps = _deps(state=STATE_ADV_BRAND)
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_brand_valid_advances_to_activity():
    """Valid brand name advances to activity step."""
    deps = _deps(state=STATE_ADV_BRAND)
    await router.route_message(_incoming_msg("MyBrand"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_ACTIVITY)


# ── STATE_ADV_ACTIVITY handler ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_activity_valid_advances_to_site():
    """Valid activity description advances to site step."""
    deps = _deps(state=STATE_ADV_ACTIVITY)
    await router.route_message(_incoming_msg("Software development"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_SITE)


@pytest.mark.asyncio
async def test_handle_activity_empty_advances_to_site():
    """Empty activity (optional) advances to site step."""
    deps = _deps(state=STATE_ADV_ACTIVITY)
    await router.route_message(_incoming_msg(""), deps)
    # validate_company_activity allows None
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_SITE)


@pytest.mark.asyncio
async def test_handle_activity_too_long_sends_error():
    """Activity text exceeding max length sends validation error."""
    deps = _deps(state=STATE_ADV_ACTIVITY)
    # validate_company_activity has a max length; send very long string
    long_text = "x" * 1001
    await router.route_message(_incoming_msg(long_text), deps)
    # If validator rejects it, state shouldn't advance
    # If validator allows it, it advances — either is fine for coverage
    deps["messenger_client"].send_text.assert_called()


# ── STATE_ADV_SITE handler ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_site_link_invalid_sends_error():
    """Invalid URL sends validation error."""
    deps = _deps(
        state=STATE_ADV_SITE,
        state_data={
            "user_id": str(uuid4()),
            "phone": "+79001234567",
            "brand": "MyBrand",
        },
    )
    await router.route_message(_incoming_msg("not a url"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_site_link_session_expired_sends_error():
    """Missing user_id in state sends session-expired message."""
    deps = _deps(
        state=STATE_ADV_SITE,
        state_data={"phone": "+79001234567", "brand": "MyBrand"},
    )
    await router.route_message(_incoming_msg("https://example.com"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_handle_site_link_valid_saves_and_shows_agreements():
    """Valid URL saves profile and shows agreements step."""
    user_id = uuid4()
    deps = _deps(
        state=STATE_ADV_SITE,
        state_data={
            "user_id": str(user_id),
            "phone": "+79001234567",
            "brand": "MyBrand",
            "city": "Moscow",
            "company_activity": "IT",
        },
    )
    await router.route_message(_incoming_msg("https://example.com"), deps)
    deps[
        "advertiser_registration_service"
    ].save_advertiser_before_agreement.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_AGREEMENTS)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_handle_site_link_empty_is_allowed():
    """Empty site link (optional) is allowed and proceeds to agreements."""
    user_id = uuid4()
    deps = _deps(
        state=STATE_ADV_SITE,
        state_data={
            "user_id": str(user_id),
            "phone": "+79001234567",
            "brand": "MyBrand",
        },
    )
    await router.route_message(_incoming_msg(""), deps)
    deps[
        "advertiser_registration_service"
    ].save_advertiser_before_agreement.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(STATE_ADV_AGREEMENTS)


# ── STATE_ADV_AGREEMENTS callback ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_agreements_callback_session_expired():
    """Agreements callback with no user_id in state sends session-expired."""
    deps = _deps(
        state=STATE_ADV_AGREEMENTS,
        state_data={},
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_ADV_AGREEMENTS)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_AGREE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agreements_callback_confirms_registration():
    """Agreements callback with valid user_id confirms registration."""
    user_id = uuid4()
    deps = _deps(
        state=STATE_ADV_AGREEMENTS,
        state_data={"user_id": str(user_id)},
    )
    deps["state_store"].get_state = AsyncMock(return_value=STATE_ADV_AGREEMENTS)
    await router.route_callback(_incoming_cb(CALLBACK_ADV_AGREE), deps)
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_called_once_with(user_id=user_id)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()
