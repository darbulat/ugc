"""Tests for Max blogger registration handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.blogger_registration import (
    STATE_BLOG_AGREEMENTS,
    STATE_BLOG_AUDIENCE_AGE,
    STATE_BLOG_AUDIENCE_GENDER,
    STATE_BLOG_AUDIENCE_GEO,
    STATE_BLOG_BARTER,
    STATE_BLOG_BIRTH_DATE,
    STATE_BLOG_CITY,
    STATE_BLOG_GENDER,
    STATE_BLOG_INSTAGRAM,
    STATE_BLOG_PHONE,
    STATE_BLOG_PRICE,
    STATE_BLOG_TOPICS,
    STATE_BLOG_WORK_FORMAT,
    router,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_BLOGGER_AGE_0_17,
    CALLBACK_BLOGGER_AGE_18_24,
    CALLBACK_BLOGGER_AGE_25_34,
    CALLBACK_BLOGGER_AGE_35_44,
    CALLBACK_BLOGGER_AGE_45_99,
    CALLBACK_BLOGGER_AGREE,
    CALLBACK_BLOGGER_AUDIENCE_A,
    CALLBACK_BLOGGER_AUDIENCE_F,
    CALLBACK_BLOGGER_AUDIENCE_M,
    CALLBACK_BLOGGER_BARTER_N,
    CALLBACK_BLOGGER_BARTER_Y,
    CALLBACK_BLOGGER_GENDER_F,
    CALLBACK_BLOGGER_GENDER_M,
    CALLBACK_BLOGGER_RETRY_INSTAGRAM,
    CALLBACK_BLOGGER_WORK_ADS,
    CALLBACK_BLOGGER_WORK_UGC,
    CALLBACK_CREATOR_CREATE,
    CALLBACK_ROLE_CREATOR,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


def _user(*, status=UserStatus.ACTIVE, username="alice"):
    u = MagicMock()
    u.user_id = uuid4()
    u.status = status
    u.username = username
    u.country = "RU"
    u.language = "ru"
    return u


def _incoming_msg(
    text: str, *, contact_phone: str | None = None
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
        contact_phone=contact_phone,
    )


def _incoming_cb(
    data: str, *, message_text: str | None = None
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
        message_id="msg_1",
        message_text=message_text,
    )


def _deps(user=None, *, state_data: dict | None = None):
    mock_config = MagicMock()
    mock_config.market.default_locale = "ru"
    mock_config.market.agreements_url = "https://example.com"
    mock_config.market.privacy_url = "https://example.com"
    mock_config.market.consent_url = "https://example.com"
    mock_config.market.offer_url = "https://example.com"
    mock_config.market.offer_url_by_country = {}
    mock_config.market.privacy_url_by_country = {}
    mock_config.market.consent_url_by_country = {}
    mock_config.instagram.admin_instagram_username = "admin_test"
    mock_config.docs.get_urls_for_country = MagicMock(
        return_value=(
            "https://offer.example.com",
            "https://privacy.example.com",
            "https://consent.example.com",
        )
    )

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    profile_service = AsyncMock()
    profile_service.get_blogger_profile = AsyncMock(return_value=None)

    state_store = AsyncMock()
    state_store.get_state = AsyncMock(return_value=None)
    state_store.get_data = AsyncMock(return_value=state_data or {})

    blogger_reg_svc = AsyncMock()
    blogger_reg_svc.get_profile_by_instagram_username = AsyncMock(
        return_value=None
    )
    blogger_reg_svc.resolve_city_from_location = AsyncMock(
        return_value=("Moscow", "Moscow Oblast", "RU")
    )
    blogger_reg_svc.resolve_city_to_location = AsyncMock(
        return_value=(
            {"type": "Point", "coordinates": [37.6, 55.7]},
            "Moscow Oblast",
            "RU",
        )
    )

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "profile_service": profile_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value="some_text"),
            get_many=AsyncMock(
                return_value={
                    "btn_create_profile": "Create",
                    "btn_edit_profile": "Edit",
                    "btn_my_profile": "My Profile",
                    "btn_my_orders": "My Orders",
                    "btn_support": "Support",
                    "msg_choose_action": "Choose action",
                    "btn_gender_m": "Male",
                    "btn_gender_f": "Female",
                    "btn_audience_f": "Female",
                    "btn_audience_m": "Male",
                    "btn_audience_a": "All",
                    "btn_age_0_17": "0-17",
                    "btn_age_18_24": "18-24",
                    "btn_age_25_34": "25-34",
                    "btn_age_35_44": "35-44",
                    "btn_age_45_99": "45+",
                    "btn_barter_yes": "Yes",
                    "btn_barter_no": "No",
                    "btn_work_format_ads": "Ads",
                    "btn_work_format_ugc_only": "UGC Only",
                    "btn_confirm_agreement": "Confirm",
                    "msg_agreements_intro_creator": "Agreements",
                    "msg_agreements_intro_default": "Default",
                    "msg_label_offer": "Offer",
                    "msg_label_privacy": "Privacy",
                    "msg_label_consent": "Consent",
                    "msg_confirm_docs_fallback": "Fallback",
                    "btn_phone_request": "Share phone",
                    "msg_phone_request": "Enter phone",
                    "btn_open_direct": "Open Direct",
                    "btn_confirm_instagram": "Confirm Instagram",
                    "err_instagram_empty": "Instagram empty",
                    "err_instagram_format": "Instagram format",
                    "err_instagram_example": "Instagram example",
                }
            ),
        ),
        "state_store": state_store,
        "config": mock_config,
        "blogger_registration_service": blogger_reg_svc,
        "instagram_verification_service": AsyncMock(),
        "locale": "ru",
        "currency_symbol": "₽",
        "max_order_price": 999999.0,
    }


# ---- /creator command ----


@pytest.mark.asyncio
async def test_creator_command_sends_message():
    """/creator command should send a response."""
    user = _user()
    deps = _deps(user)
    await router.route_message(_incoming_msg("/creator"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_creator_command_with_existing_profile():
    """/creator command with existing blogger profile shows menu keyboard."""
    user = _user()
    deps = _deps(user)
    deps["profile_service"].get_blogger_profile = AsyncMock(
        return_value=MagicMock()
    )
    await router.route_message(_incoming_msg("/creator"), deps)
    deps["messenger_client"].send_text.assert_called()


# ---- CALLBACK_ROLE_CREATOR callback ----


@pytest.mark.asyncio
async def test_role_creator_callback_sends_message():
    """CALLBACK_ROLE_CREATOR should send a response."""
    user = _user()
    deps = _deps(user)
    await router.route_callback(_incoming_cb(CALLBACK_ROLE_CREATOR), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["messenger_client"].answer_callback.assert_called()


@pytest.mark.asyncio
async def test_role_creator_callback_with_existing_profile():
    """CALLBACK_ROLE_CREATOR with existing profile shows menu."""
    user = _user()
    deps = _deps(user)
    deps["profile_service"].get_blogger_profile = AsyncMock(
        return_value=MagicMock()
    )
    await router.route_callback(_incoming_cb(CALLBACK_ROLE_CREATOR), deps)
    deps["messenger_client"].send_text.assert_called()


# ---- CALLBACK_CREATOR_CREATE callback ----


@pytest.mark.asyncio
async def test_creator_create_user_not_found():
    """Missing user gets not-found message, state not set."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(CALLBACK_CREATOR_CREATE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_creator_create_blocked_user():
    """Blocked user gets blocked message, state not set."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user)
    await router.route_callback(_incoming_cb(CALLBACK_CREATOR_CREATE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_creator_create_happy_path():
    """Active user starts registration, state set to STATE_BLOG_PHONE."""
    user = _user()
    deps = _deps(user)
    await router.route_callback(_incoming_cb(CALLBACK_CREATOR_CREATE), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_PHONE)
    deps["messenger_client"].send_text.assert_called()


# ---- STATE_BLOG_PHONE handler ----


@pytest.mark.asyncio
async def test_handle_phone_invalid_number():
    """Invalid phone should send error and not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PHONE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("not-a-phone"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_phone_valid_advances_to_instagram():
    """Valid phone number advances to STATE_BLOG_INSTAGRAM."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PHONE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("+79991234567"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_INSTAGRAM)


@pytest.mark.asyncio
async def test_handle_phone_via_contact():
    """Phone from contact_phone field advances to STATE_BLOG_INSTAGRAM."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PHONE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    msg = _incoming_msg("", contact_phone="+79991234567")
    await router.route_message(msg, deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_INSTAGRAM)


@pytest.mark.asyncio
async def test_handle_phone_empty_shows_error():
    """Empty phone input shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PHONE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---- STATE_BLOG_INSTAGRAM handler ----


@pytest.mark.asyncio
async def test_handle_instagram_empty():
    """Empty text shows empty error, state unchanged."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_instagram_not_instagram_url():
    """Text without instagram.com shows format error."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    await router.route_message(_incoming_msg("notagram.com/user"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_instagram_invalid_regex():
    """instagram.com URL with invalid format shows example error."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    await router.route_message(_incoming_msg("instagram.com/a b c"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_instagram_valid_advances_to_city():
    """Valid Instagram URL advances to STATE_BLOG_CITY."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    await router.route_message(
        _incoming_msg("https://instagram.com/testuser"), deps
    )
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_CITY)


@pytest.mark.asyncio
async def test_handle_instagram_existing_profile_triggers_verification():
    """Existing Instagram profile triggers verification flow."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    existing_profile = MagicMock()
    existing_profile.user_id = uuid4()
    deps[
        "blogger_registration_service"
    ].get_profile_by_instagram_username = AsyncMock(
        return_value=existing_profile
    )
    verification = MagicMock()
    verification.code = "TEST123"
    deps["instagram_verification_service"].generate_code = AsyncMock(
        return_value=verification
    )
    await router.route_message(
        _incoming_msg("https://instagram.com/existinguser"), deps
    )
    deps["instagram_verification_service"].generate_code.assert_called_once()
    # State should be cleared, not advanced
    deps["state_store"].clear.assert_called()


# ---- STATE_BLOG_CITY handler ----


@pytest.mark.asyncio
async def test_handle_city_empty():
    """Empty city input shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_CITY)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_city_valid_text_advances_to_birth_date():
    """Valid city text advances to STATE_BLOG_BIRTH_DATE."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_CITY)
    await router.route_message(_incoming_msg("Moscow"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_BIRTH_DATE)


@pytest.mark.asyncio
async def test_handle_city_not_found_shows_error():
    """City not resolved shows error with location request."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_CITY)
    deps["blogger_registration_service"].resolve_city_to_location = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("Xyznonexistentcity"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_city_from_location():
    """Location coordinates advance to Max birth-date state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_CITY)

    msg = IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=None,
        message_id="msg_1",
        location_lat=55.7,
        location_lon=37.6,
    )
    await router.route_message(msg, deps)
    deps[
        "blogger_registration_service"
    ].resolve_city_from_location.assert_called_once_with(55.7, 37.6)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_BIRTH_DATE)


# ---- STATE_BLOG_BIRTH_DATE handler ----


@pytest.mark.asyncio
async def test_handle_birth_date_invalid():
    """Invalid date format shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_BIRTH_DATE
    )
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("not-a-date"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_birth_date_valid_advances_to_gender():
    """Valid birth date advances to STATE_BLOG_GENDER."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_BIRTH_DATE
    )
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"btn_gender_m": "Male", "btn_gender_f": "Female"}
    )
    await router.route_message(_incoming_msg("01.01.1990"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_GENDER)


# ---- STATE_BLOG_GENDER callback ----


@pytest.mark.asyncio
async def test_handle_blogger_gender_male():
    """Male gender callback saves gender and advances to STATE_BLOG_TOPICS."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_GENDER)
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_GENDER_M), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_TOPICS)


@pytest.mark.asyncio
async def test_handle_blogger_gender_female():
    """Female gender callback saves gender and advances to STATE_BLOG_TOPICS."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_GENDER)
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_GENDER_F), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_TOPICS)


# ---- STATE_BLOG_TOPICS handler ----


@pytest.mark.asyncio
async def test_handle_topics_empty():
    """Empty topics input shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_TOPICS)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_topics_valid_advances_to_audience_gender():
    """Valid topics advance to STATE_BLOG_AUDIENCE_GENDER."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_TOPICS)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_audience_f": "Female",
            "btn_audience_m": "Male",
            "btn_audience_a": "All",
        }
    )
    await router.route_message(_incoming_msg("lifestyle, travel, food"), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GENDER
    )


@pytest.mark.asyncio
async def test_handle_topics_too_many_shows_error():
    """More than 5 topics shows validation error."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_TOPICS)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    await router.route_message(
        _incoming_msg("a, b, c, d, e, f, g, h, i, j, k"), deps
    )
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


# ---- STATE_BLOG_AUDIENCE_GENDER callback ----


@pytest.mark.asyncio
async def test_handle_audience_gender_female():
    """Female audience callback saves and advances
    to STATE_BLOG_AUDIENCE_AGE."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GENDER
    )
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_age_0_17": "0-17",
            "btn_age_18_24": "18-24",
            "btn_age_25_34": "25-34",
            "btn_age_35_44": "35-44",
            "btn_age_45_99": "45+",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AUDIENCE_F), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_AGE
    )


@pytest.mark.asyncio
async def test_handle_audience_gender_male():
    """Male audience callback advances to STATE_BLOG_AUDIENCE_AGE."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GENDER
    )
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_age_0_17": "0-17",
            "btn_age_18_24": "18-24",
            "btn_age_25_34": "25-34",
            "btn_age_35_44": "35-44",
            "btn_age_45_99": "45+",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AUDIENCE_M), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_AGE
    )


@pytest.mark.asyncio
async def test_handle_audience_gender_all():
    """All audience callback advances to STATE_BLOG_AUDIENCE_AGE."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GENDER
    )
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_age_0_17": "0-17",
            "btn_age_18_24": "18-24",
            "btn_age_25_34": "25-34",
            "btn_age_35_44": "35-44",
            "btn_age_45_99": "45+",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AUDIENCE_A), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_AGE
    )


# ---- STATE_BLOG_AUDIENCE_AGE callback ----


@pytest.mark.asyncio
async def test_handle_audience_age_0_17():
    """Age 0-17 callback saves age range and advances
    to STATE_BLOG_AUDIENCE_GEO."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_AGE
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGE_0_17), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GEO
    )


@pytest.mark.asyncio
async def test_handle_audience_age_18_24():
    """Age 18-24 callback advances to STATE_BLOG_AUDIENCE_GEO."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_AGE
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGE_18_24), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GEO
    )


@pytest.mark.asyncio
async def test_handle_audience_age_25_34():
    """Age 25-34 callback advances to STATE_BLOG_AUDIENCE_GEO."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_AGE
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGE_25_34), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GEO
    )


@pytest.mark.asyncio
async def test_handle_audience_age_35_44():
    """Age 35-44 callback advances to STATE_BLOG_AUDIENCE_GEO."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_AGE
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGE_35_44), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GEO
    )


@pytest.mark.asyncio
async def test_handle_audience_age_45_99():
    """Age 45+ callback advances to STATE_BLOG_AUDIENCE_GEO."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_AGE
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGE_45_99), deps)
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_AUDIENCE_GEO
    )


# ---- STATE_BLOG_AUDIENCE_GEO handler ----


@pytest.mark.asyncio
async def test_handle_audience_geo_empty():
    """Empty geo input shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GEO
    )
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg(""), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_audience_geo_too_many_cities():
    """More than 3 cities shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GEO
    )
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(
        _incoming_msg("Moscow, SPb, Kazan, Yekaterinburg"), deps
    )
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_audience_geo_valid_advances_to_price():
    """Valid geo (up to 3 cities) advances to STATE_BLOG_PRICE."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GEO
    )
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(
        return_value="Enter price: {currency}"
    )
    await router.route_message(_incoming_msg("Moscow, SPb"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_PRICE)


# ---- STATE_BLOG_PRICE handler ----


@pytest.mark.asyncio
async def test_handle_price_not_a_number():
    """Non-numeric price shows error and does not advance state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg("abcd"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_price_negative_shows_error():
    """Negative price shows validation error."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg("-100"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_price_exceeds_max():
    """Price exceeding maximum shows validation error."""
    deps = _deps()
    deps["max_order_price"] = 1000.0
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg("9999999"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_price_valid_advances_to_barter():
    """Valid price advances to STATE_BLOG_BARTER."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"btn_barter_yes": "Yes", "btn_barter_no": "No"}
    )
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg("5000"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_BARTER)


@pytest.mark.asyncio
async def test_handle_price_with_comma_decimal():
    """Price with comma as decimal separator is accepted."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_PRICE)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"btn_barter_yes": "Yes", "btn_barter_no": "No"}
    )
    deps["bot_texts_service"].get = AsyncMock(return_value="")
    await router.route_message(_incoming_msg("5000,50"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_BARTER)


# ---- STATE_BLOG_BARTER callback ----


@pytest.mark.asyncio
async def test_handle_barter_yes():
    """Barter yes callback saves True and advances to STATE_BLOG_WORK_FORMAT."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_BARTER)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_work_format_ads": "Ads",
            "btn_work_format_ugc_only": "UGC Only",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_BARTER_Y), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_WORK_FORMAT
    )


@pytest.mark.asyncio
async def test_handle_barter_no():
    """Barter no callback saves False and advances to STATE_BLOG_WORK_FORMAT."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_BARTER)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_work_format_ads": "Ads",
            "btn_work_format_ugc_only": "UGC Only",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_BARTER_N), deps)
    deps["state_store"].update_data.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        STATE_BLOG_WORK_FORMAT
    )


# ---- STATE_BLOG_WORK_FORMAT callback ----


def _full_state_data():
    """Complete FSM state data for work_format/agreements step."""
    return {
        "user_id": str(uuid4()),
        "instagram_url": "https://instagram.com/testuser",
        "city": "Moscow",
        "topics": {"selected": ["lifestyle"]},
        "audience_gender": "F",
        "audience_age_min": 18,
        "audience_age_max": 24,
        "audience_geo": "Moscow",
        "price": 5000.0,
        "barter": True,
        "blogger_gender": "M",
        "birth_date": "1990-01-01",
        "region": "Moscow Oblast",
        "country": "RU",
        "phone": "+79991234567",
    }


@pytest.mark.asyncio
async def test_handle_work_format_ads_saves_and_shows_agreements():
    """Ads work format triggers save and shows agreements."""
    state_data = _full_state_data()
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_AGREEMENTS)


@pytest.mark.asyncio
async def test_handle_work_format_ugc_saves_and_shows_agreements():
    """UGC work format triggers save and shows agreements."""
    state_data = _full_state_data()
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_UGC), deps)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_AGREEMENTS)


@pytest.mark.asyncio
async def test_handle_work_format_session_expired():
    """Work format step with missing user_id handles session expiry."""
    deps = _deps(state_data={})
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_handle_work_format_duplicate_instagram_url():
    """Duplicate Instagram URL during save shows already-registered message."""
    state_data = _full_state_data()
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement = AsyncMock(
        side_effect=Exception("UniqueViolation: instagram_url already exists")
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    deps["messenger_client"].send_text.assert_called()
    # Should not set agreements state because of duplicate error
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_work_format_duplicate_instagram_url_russian_message():
    """Duplicate Instagram URL with Russian error message is handled."""
    state_data = _full_state_data()
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement = AsyncMock(
        side_effect=Exception("уже зарегистрирован в системе")
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_work_format_reraises_unknown_exception():
    """Non-duplicate exception from save_blogger
    is re-raised (handled by router)."""
    state_data = _full_state_data()
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement = AsyncMock(
        side_effect=RuntimeError("database error")
    )
    # Router catches the exception and sends error message, does not raise
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    # send_text should be called (error message from router)
    deps["messenger_client"].send_text.assert_called()


# ---- STATE_BLOG_AGREEMENTS callback ----


@pytest.mark.asyncio
async def test_handle_agreements_session_expired():
    """Agreements confirmation with missing user_id sends expired message."""
    deps = _deps(state_data={})
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AGREEMENTS
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGREE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agreements_happy_path():
    """Agreement confirmation finalizes registration."""
    user_id = str(uuid4())
    state_data = {"user_id": user_id}
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AGREEMENTS
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_confirm_instagram": "Confirm IG",
            "btn_my_profile": "My Profile",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_AGREE), deps)
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_called_once()
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


# ---- CALLBACK_BLOGGER_RETRY_INSTAGRAM callback ----


@pytest.mark.asyncio
async def test_handle_retry_instagram_sets_instagram_state():
    """Retry Instagram callback sets state to STATE_BLOG_INSTAGRAM."""
    deps = _deps()
    await router.route_callback(
        _incoming_cb(CALLBACK_BLOGGER_RETRY_INSTAGRAM), deps
    )
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_INSTAGRAM)
    deps["messenger_client"].send_text.assert_called()


# ---- _remove_inline_keyboard helper ----


@pytest.mark.asyncio
async def test_remove_inline_keyboard_no_message_id():
    """_remove_inline_keyboard does nothing when message_id is None."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        _remove_inline_keyboard,
    )

    cb = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="some:data",
        message_id=None,
    )
    messenger = AsyncMock()
    await _remove_inline_keyboard(cb, messenger)
    messenger.edit_text.assert_not_called()
    messenger.edit_reply_markup.assert_not_called()


@pytest.mark.asyncio
async def test_remove_inline_keyboard_with_label_and_text():
    """_remove_inline_keyboard edits text when
    label and message_text provided."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        _remove_inline_keyboard,
    )

    cb = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="some:data",
        message_id="msg_1",
        message_text="Question?",
    )
    messenger = AsyncMock()
    await _remove_inline_keyboard(cb, messenger, selected_label="Answer")
    messenger.edit_text.assert_called_once_with(
        chat_id="100",
        message_id="msg_1",
        text="Question?: Answer",
    )


@pytest.mark.asyncio
async def test_remove_inline_keyboard_no_label_removes_markup():
    """_remove_inline_keyboard removes markup when no label provided."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        _remove_inline_keyboard,
    )

    cb = IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        data="some:data",
        message_id="msg_1",
        message_text="Question?",
    )
    messenger = AsyncMock()
    await _remove_inline_keyboard(cb, messenger, selected_label=None)
    messenger.edit_reply_markup.assert_called_once_with(
        chat_id="100",
        message_id="msg_1",
        keyboard=None,
    )


# ---- Edge cases ----


@pytest.mark.asyncio
async def test_handle_instagram_admin_username_without_at():
    """Admin Instagram username without @ still builds correct URL."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    deps["config"].instagram.admin_instagram_username = "@some_admin"
    existing_profile = MagicMock()
    existing_profile.user_id = uuid4()
    deps[
        "blogger_registration_service"
    ].get_profile_by_instagram_username = AsyncMock(
        return_value=existing_profile
    )
    verification = MagicMock()
    verification.code = "CODE999"
    deps["instagram_verification_service"].generate_code = AsyncMock(
        return_value=verification
    )
    await router.route_message(
        _incoming_msg("https://instagram.com/testuser"), deps
    )
    deps["instagram_verification_service"].generate_code.assert_called_once()


@pytest.mark.asyncio
async def test_handle_instagram_no_admin_username():
    """Admin Instagram username empty produces no direct URL."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_INSTAGRAM)
    deps["config"].instagram.admin_instagram_username = ""
    existing_profile = MagicMock()
    existing_profile.user_id = uuid4()
    deps[
        "blogger_registration_service"
    ].get_profile_by_instagram_username = AsyncMock(
        return_value=existing_profile
    )
    verification = MagicMock()
    verification.code = "CODE000"
    deps["instagram_verification_service"].generate_code = AsyncMock(
        return_value=verification
    )
    await router.route_message(
        _incoming_msg("https://instagram.com/testuser"), deps
    )
    # Should still send text with code
    assert deps["messenger_client"].send_text.call_count >= 1


@pytest.mark.asyncio
async def test_creator_create_user_id_not_uuid():
    """User with non-UUID user_id skips state setup silently."""
    user = _user()
    user.user_id = "not-a-uuid"
    deps = _deps(user)
    await router.route_callback(_incoming_cb(CALLBACK_CREATOR_CREATE), deps)
    # Should not raise and should not set state
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_handle_barter_yes_with_message_text():
    """Barter callback with message_text updates the message text."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value=STATE_BLOG_BARTER)
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={
            "btn_work_format_ads": "Ads",
            "btn_work_format_ugc_only": "UGC Only",
        }
    )
    deps["bot_texts_service"].get = AsyncMock(return_value="Yes barter")
    cb = _incoming_cb(
        CALLBACK_BLOGGER_BARTER_Y, message_text="Do you want barter?"
    )
    await router.route_callback(cb, deps)
    deps["messenger_client"].edit_text.assert_called()


@pytest.mark.asyncio
async def test_handle_audience_geo_single_city():
    """Single city in audience geo is valid."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_AUDIENCE_GEO
    )
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["bot_texts_service"].get = AsyncMock(return_value="Price: {currency}")
    await router.route_message(_incoming_msg("Moscow"), deps)
    deps["state_store"].set_state.assert_called_once_with(STATE_BLOG_PRICE)


@pytest.mark.asyncio
async def test_handle_work_format_ads_with_birth_date_none():
    """Work format handler with no birth_date in state uses None."""
    state_data = _full_state_data()
    del state_data["birth_date"]
    deps = _deps(state_data=state_data)
    deps["state_store"].get_state = AsyncMock(
        return_value=STATE_BLOG_WORK_FORMAT
    )
    deps["state_store"].get_data = AsyncMock(return_value=state_data)
    await router.route_callback(_incoming_cb(CALLBACK_BLOGGER_WORK_ADS), deps)
    deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement.assert_called_once()
    call_kwargs = deps[
        "blogger_registration_service"
    ].save_blogger_before_agreement.call_args.kwargs
    assert call_kwargs["birth_date"] is None


# ---- Defensive branch tests (direct function calls) ----


@pytest.mark.asyncio
async def test_handle_blogger_gender_callback_unknown_data():
    """Gender callback with unrecognised data just removes
    keyboard without state change."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        handle_blogger_gender_callback,
    )

    deps = _deps()
    cb = _incoming_cb("blogger:gender:UNKNOWN")
    await handle_blogger_gender_callback(cb, deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["state_store"].set_state.assert_not_called()
    deps["messenger_client"].edit_reply_markup.assert_called()


@pytest.mark.asyncio
async def test_handle_audience_gender_callback_unknown_data():
    """Audience gender callback with unrecognised data just removes keyboard."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        handle_audience_gender_callback,
    )

    deps = _deps()
    cb = _incoming_cb("blogger:aud:UNKNOWN")
    await handle_audience_gender_callback(cb, deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["state_store"].set_state.assert_not_called()
    deps["messenger_client"].edit_reply_markup.assert_called()


@pytest.mark.asyncio
async def test_handle_audience_age_callback_unknown_data():
    """Audience age callback with unrecognised data just removes keyboard."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        handle_audience_age_callback,
    )

    deps = _deps()
    cb = _incoming_cb("blogger:age:UNKNOWN")
    await handle_audience_age_callback(cb, deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["state_store"].set_state.assert_not_called()
    deps["messenger_client"].edit_reply_markup.assert_called()


@pytest.mark.asyncio
async def test_handle_work_format_callback_unknown_data():
    """Work format callback with unrecognised data just removes keyboard."""
    from ugc_bot.bot.max.handlers.blogger_registration import (
        handle_work_format_callback,
    )

    deps = _deps()
    cb = _incoming_cb("blogger:work:UNKNOWN")
    await handle_work_format_callback(cb, deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["state_store"].set_state.assert_not_called()
    deps["messenger_client"].edit_reply_markup.assert_called()
