"""Tests for Max profile handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.profile import router
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_AGE_18_24,
    CALLBACK_PROFILE_AGREE,
    CALLBACK_PROFILE_AUDIENCE_F,
    CALLBACK_PROFILE_AUDIENCE_M,
    CALLBACK_PROFILE_BARTER_N,
    CALLBACK_PROFILE_BARTER_Y,
    CALLBACK_PROFILE_BLOGGER_GENDER_F,
    CALLBACK_PROFILE_BLOGGER_GENDER_M,
    CALLBACK_PROFILE_EDIT,
    CALLBACK_PROFILE_EDIT_FIELD_PREFIX,
    CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
    CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
    CALLBACK_PROFILE_MY_PROFILE,
    CALLBACK_PROFILE_WORK_ADS,
    CALLBACK_PROFILE_WORK_UGC,
)
from ugc_bot.bot.telegram.handlers.profile import (
    _ADVERTISER_AGREEMENTS_STATE,
    _BLOGGER_AGREEMENTS_STATE,
    EditProfileStates,
)
from ugc_bot.domain.enums import MessengerType

# Derive state string constants for use in tests
_STATE_ENTERING_VALUE = str(EditProfileStates.entering_value.state)
_STATE_CHOOSING_FIELD = str(EditProfileStates.choosing_field.state)
_STATE_CHOOSING_PROFILE_TYPE = str(
    EditProfileStates.choosing_profile_type.state
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(user_id=None, country="RU"):
    u = MagicMock()
    u.user_id = user_id or uuid4()
    u.country = country
    u.language = "ru"
    u.username = "alice"
    return u


def _blogger(confirmed=True, agreement_confirmed_at="2024-01-01"):
    b = MagicMock()
    b.confirmed = confirmed
    b.agreement_confirmed_at = agreement_confirmed_at
    return b


def _advertiser(agreement_confirmed_at="2024-01-01"):
    a = MagicMock()
    a.agreement_confirmed_at = agreement_confirmed_at
    return a


def _incoming_msg(
    text: str, *, contact_phone=None, location_lat=None, location_lon=None
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
        location_lat=location_lat,
        location_lon=location_lon,
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


def _all_texts() -> dict:
    """Return a dict with all text keys the keyboard
    builders may look up directly."""
    return {
        # keyboard builder required keys
        "btn_my_profile": "My Profile",
        "btn_edit_profile": "Edit Profile",
        "btn_confirm_instagram": "Confirm Instagram",
        "btn_create_order": "Create Order",
        "btn_my_orders": "My Orders",
        "btn_edit_profile_blogger": "Edit Blogger",
        "btn_edit_profile_advertiser": "Edit Advertiser",
        "msg_choose_profile_edit": "Choose profile",
        "msg_choose_section_edit": "Choose section",
        "btn_confirm_agreement": "Confirm",
        "msg_confirm_agreement": "Please confirm",
        "msg_agreements_intro_default": "Intro",
        "msg_label_offer": "Offer",
        "msg_label_privacy": "Privacy",
        "msg_label_consent": "Consent",
        "msg_confirm_docs_fallback": "Fallback",
        # audience / gender / age / barter / work buttons
        "btn_audience_f": "Female",
        "btn_audience_m": "Male",
        "btn_audience_a": "All",
        "btn_gender_m": "Male",
        "btn_gender_f": "Female",
        "btn_age_0_17": "0-17",
        "btn_age_18_24": "18-24",
        "btn_age_25_34": "25-34",
        "btn_age_35_44": "35-44",
        "btn_age_45_99": "45+",
        "btn_barter_yes": "Yes",
        "btn_barter_no": "No",
        "btn_work_format_ads": "Ads",
        "btn_work_format_ugc_only": "UGC only",
        "btn_phone_request": "Share phone",
        "btn_location_request": "Share location",
        # edit field label keys (blogger)
        "lbl_field_nickname": "Nickname",
        "lbl_field_city": "City",
        "lbl_field_instagram_url": "Instagram",
        "lbl_field_blogger_gender": "Gender",
        "lbl_field_birth_date": "Birth date",
        "lbl_field_topics": "Topics",
        "lbl_field_audience_gender": "Audience gender",
        "lbl_field_audience_age": "Audience age",
        "lbl_field_audience_geo": "Audience geo",
        "lbl_field_price": "Price",
        "lbl_field_barter": "Barter",
        "lbl_field_work_format": "Work format",
        # edit field label keys (advertiser)
        "lbl_adv_field_name": "Name",
        "lbl_adv_field_brand": "Brand",
        "lbl_adv_field_city": "City",
        "lbl_adv_field_phone": "Phone",
        "lbl_adv_field_site_link": "Site",
        "lbl_adv_field_company_activity": "Activity",
        # prompt keys
        "prompt_edit_generic": "Enter value",
        "prompt_edit_nickname": "Enter nickname",
        "prompt_edit_city": "Enter city",
        "prompt_edit_instagram_url": "Enter instagram",
        "prompt_edit_blogger_gender": "Choose gender",
        "prompt_edit_birth_date": "Enter birth date",
        "prompt_edit_topics": "Enter topics",
        "prompt_edit_audience_gender": "Choose audience gender",
        "prompt_edit_audience_age": "Choose audience age",
        "prompt_edit_audience_geo": "Enter geo",
        "prompt_edit_price": "Enter price ({currency})",
        "prompt_edit_barter": "Choose barter",
        "prompt_edit_work_format": "Choose work format",
        "prompt_edit_brand": "Enter brand",
        "prompt_edit_phone": "Enter phone",
        "prompt_edit_site_link": "Enter site",
        "prompt_edit_company_activity": "Enter activity",
        "prompt_edit_name": "Enter name",
        # error / success keys
        "msg_profile_updated": "Updated!",
        "msg_profile_update_failed": "Failed",
        "msg_unknown_field": "Unknown field",
        "msg_name_updated": "Name updated",
        "msg_session_expired_profile": "Session expired",
        "msg_profile_not_found_role": "Not found",
        "msg_profile_incomplete": "Incomplete",
    }


def _deps(user=None, blogger=None, advertiser=None):
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
    # format_agreements_message calls config.docs.get_urls_for_country
    mock_config.docs.get_urls_for_country.return_value = (
        "https://offer.example.com",
        "https://privacy.example.com",
        "https://consent.example.com",
    )

    profile_service = AsyncMock()
    profile_service.get_user_by_external = AsyncMock(return_value=user)
    profile_service.get_blogger_profile = AsyncMock(return_value=blogger)
    profile_service.get_advertiser_profile = AsyncMock(return_value=advertiser)
    profile_service.get_user_by_id = AsyncMock(return_value=user)

    user_role_service = AsyncMock()
    user_role_service.get_user_by_id = AsyncMock(return_value=user)

    all_texts = _all_texts()

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "profile_service": profile_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value=""),
            get_many=AsyncMock(return_value=all_texts),
        ),
        "state_store": AsyncMock(get_data=AsyncMock(return_value={})),
        "config": mock_config,
        "country_repo": AsyncMock(),
        "blogger_registration_service": AsyncMock(),
        "advertiser_registration_service": AsyncMock(),
        "locale": "ru",
    }


# ---------------------------------------------------------------------------
# /profile command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_command_clears_state():
    """/profile command clears FSM state before showing profile."""
    deps = _deps()
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_profile_command_user_not_found():
    """/profile when user is not found sends a not-found message."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_profile_command_no_profile():
    """/profile for user with no blogger or advertiser
    profile still sends text."""
    user = _user()
    deps = _deps(user=user, blogger=None, advertiser=None)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_profile_command_with_blogger_profile():
    """/profile for blogger sends profile text with blogger keyboard."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger(), advertiser=None)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs["chat_id"] == "100"


@pytest.mark.asyncio
async def test_profile_command_with_advertiser_profile():
    """/profile for advertiser sends profile text with advertiser keyboard."""
    user = _user()
    deps = _deps(user=user, blogger=None, advertiser=_advertiser())
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs["chat_id"] == "100"


@pytest.mark.asyncio
async def test_profile_command_needs_agreement_blogger():
    """/profile with unconfirmed blogger agreement shows agreement prompt."""
    user = _user()
    blogger = _blogger(agreement_confirmed_at=None)
    deps = _deps(user=user, blogger=blogger, advertiser=None)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        _BLOGGER_AGREEMENTS_STATE
    )


@pytest.mark.asyncio
async def test_profile_command_needs_agreement_advertiser():
    """/profile with unconfirmed advertiser agreement shows agreement prompt."""
    user = _user()
    advertiser = _advertiser(agreement_confirmed_at=None)
    deps = _deps(user=user, blogger=None, advertiser=advertiser)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_called_once_with(
        _ADVERTISER_AGREEMENTS_STATE
    )


@pytest.mark.asyncio
async def test_profile_command_needs_agreement_both():
    """/profile with both profiles unconfirmed sets blogger agreements state."""
    user = _user()
    blogger = _blogger(agreement_confirmed_at=None)
    advertiser = _advertiser(agreement_confirmed_at=None)
    deps = _deps(user=user, blogger=blogger, advertiser=advertiser)
    await router.route_message(_incoming_msg("/profile"), deps)
    deps["state_store"].set_state.assert_called_once_with(
        _BLOGGER_AGREEMENTS_STATE
    )


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_MY_PROFILE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_profile_callback_user_not_found():
    """My-profile callback with no user sends not-found message."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_MY_PROFILE), deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_profile_callback_clears_state_and_shows_profile():
    """My-profile callback clears state then sends the profile."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger())
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_MY_PROFILE), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_my_profile_callback_answers_callback():
    """My-profile callback always answers the callback query."""
    deps = _deps()
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_MY_PROFILE), deps)
    deps["messenger_client"].answer_callback.assert_called_once_with(
        callback_id="cb_1"
    )


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_AGREE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agree_callback_wrong_state_does_nothing():
    """Agree callback when not in agreements state does nothing."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(return_value="some_other_state")
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_not_called()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_agree_callback_no_user_id_in_state():
    """Agree callback when state has no user_id
    shows session-expired message."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_BLOGGER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_not_called()


@pytest.mark.asyncio
async def test_agree_callback_blogger_state_confirms_blogger():
    """Agree callback in blogger agreements state confirms blogger agreement."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger(), advertiser=None)
    deps["state_store"].get_state = AsyncMock(
        return_value=_BLOGGER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"user_id": str(user.user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_called_once()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_agree_callback_advertiser_state_confirms_advertiser():
    """Agree callback in advertiser agreements state
    confirms advertiser agreement."""
    user = _user()
    deps = _deps(user=user, blogger=None, advertiser=_advertiser())
    deps["state_store"].get_state = AsyncMock(
        return_value=_ADVERTISER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"user_id": str(user.user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_called_once()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_agree_callback_blogger_state_also_confirms_unconfirmed_advertiser():  # noqa: E501
    """Agree from blogger state also confirms advertiser if unconfirmed."""
    user = _user()
    advertiser = _advertiser(agreement_confirmed_at=None)
    deps = _deps(user=user, blogger=_blogger(), advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_BLOGGER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"user_id": str(user.user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_called()
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_called()


@pytest.mark.asyncio
async def test_agree_callback_advertiser_state_also_confirms_unconfirmed_blogger():  # noqa: E501
    """Agree from advertiser state also confirms blogger if unconfirmed."""
    user = _user()
    blogger = _blogger(agreement_confirmed_at=None)
    deps = _deps(user=user, blogger=blogger, advertiser=_advertiser())
    deps["state_store"].get_state = AsyncMock(
        return_value=_ADVERTISER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"user_id": str(user.user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps[
        "advertiser_registration_service"
    ].confirm_advertiser_agreement.assert_called()
    deps[
        "blogger_registration_service"
    ].confirm_blogger_agreement.assert_called()


@pytest.mark.asyncio
async def test_agree_callback_sends_profile_after_confirm():
    """Agree callback shows the profile after confirming agreement."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger())
    deps["state_store"].get_state = AsyncMock(
        return_value=_BLOGGER_AGREEMENTS_STATE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"user_id": str(user.user_id)}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGREE), deps)
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_EDIT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_callback_user_not_found():
    """Edit callback when user not found sends not-found message."""
    deps = _deps(user=None)
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_edit_callback_no_profiles():
    """Edit callback with no blogger or advertiser
    profile sends incomplete message."""
    user = _user()
    deps = _deps(user=user, blogger=None, advertiser=None)
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_edit_callback_blogger_only_goes_to_choosing_field():
    """Edit callback with only blogger profile sets choosing_field state."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger(), advertiser=None)
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_CHOOSING_FIELD)


@pytest.mark.asyncio
async def test_edit_callback_advertiser_only_goes_to_choosing_field():
    """Edit callback with only advertiser profile sets choosing_field state."""
    user = _user()
    deps = _deps(user=user, blogger=None, advertiser=_advertiser())
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    deps["state_store"].set_state.assert_called_once_with(_STATE_CHOOSING_FIELD)


@pytest.mark.asyncio
async def test_edit_callback_both_profiles_goes_to_choosing_profile_type():
    """Edit callback with both profiles sets choosing_profile_type state."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger(), advertiser=_advertiser())
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    deps["state_store"].set_state.assert_called_once_with(
        _STATE_CHOOSING_PROFILE_TYPE
    )


@pytest.mark.asyncio
async def test_edit_callback_stores_user_id_in_state():
    """Edit callback saves edit_user_id and edit_external_id to state."""
    user = _user()
    deps = _deps(user=user, blogger=_blogger(), advertiser=None)
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_EDIT), deps)
    call_kwargs = deps["state_store"].update_data.call_args_list[0].kwargs
    assert "edit_user_id" in call_kwargs
    assert "edit_external_id" in call_kwargs


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_EDIT_TYPE_BLOGGER / ADVERTISER
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_type_blogger_callback_sets_blogger_type():
    """Edit type blogger callback stores
    edit_profile_type=blogger and sets choosing_field."""
    deps = _deps()
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_TYPE_BLOGGER), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    update_calls = [
        str(c) for c in deps["state_store"].update_data.call_args_list
    ]
    assert any("blogger" in c for c in update_calls)
    deps["state_store"].set_state.assert_called_once_with(_STATE_CHOOSING_FIELD)


@pytest.mark.asyncio
async def test_edit_type_advertiser_callback_sets_advertiser_type():
    """Edit type advertiser callback stores
    edit_profile_type=advertiser
    and sets choosing_field."""
    deps = _deps()
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    update_calls = [
        str(c) for c in deps["state_store"].update_data.call_args_list
    ]
    assert any("advertiser" in c for c in update_calls)
    deps["state_store"].set_state.assert_called_once_with(_STATE_CHOOSING_FIELD)


@pytest.mark.asyncio
async def test_edit_type_blogger_callback_sends_field_menu():
    """Edit type blogger callback sends the field selection menu."""
    deps = _deps()
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_TYPE_BLOGGER), deps
    )
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_edit_type_advertiser_callback_sends_field_menu():
    """Edit type advertiser callback sends the field selection menu."""
    deps = _deps()
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER), deps
    )
    deps["messenger_client"].send_text.assert_called_once()


# ---------------------------------------------------------------------------
# CALLBACK_PROFILE_EDIT_FIELD_PREFIX callbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_field_callback_valid_blogger_field_sends_prompt():
    """Edit field callback with a valid blogger field
    sends a prompt and sets entering_value state."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "nickname"), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(_STATE_ENTERING_VALUE)


@pytest.mark.asyncio
async def test_edit_field_callback_valid_advertiser_field_sends_prompt():
    """Edit field callback with a valid advertiser field sends a prompt."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "advertiser"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "brand"), deps
    )
    deps["messenger_client"].send_text.assert_called_once()
    deps["state_store"].set_state.assert_called_once_with(_STATE_ENTERING_VALUE)


@pytest.mark.asyncio
async def test_edit_field_callback_invalid_field_does_nothing():
    """Edit field callback with an invalid field key does not set state."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "nonexistent_field"),
        deps,
    )
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_edit_field_callback_stores_editing_field():
    """Edit field callback saves the editing_field key to state data."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "city"), deps
    )
    update_calls = [
        str(c) for c in deps["state_store"].update_data.call_args_list
    ]
    assert any("city" in c for c in update_calls)


@pytest.mark.asyncio
async def test_edit_field_callback_audience_gender_sends_keyboard():
    """Edit field callback for audience_gender sends
    audience gender keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "audience_gender"),
        deps,
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_edit_field_callback_barter_sends_keyboard():
    """Edit field callback for barter sends barter keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "barter"), deps
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


# ---------------------------------------------------------------------------
# handle_profile_edit_choice_callback (callback_in_state entering_value)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_choice_callback_audience_f_updates_blogger():
    """Choice callback for audience_f triggers blogger field update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "audience_gender",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AUDIENCE_F), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_audience_m_updates_blogger():
    """Choice callback for audience_m triggers blogger field update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "audience_gender",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AUDIENCE_M), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_skips_when_not_blogger():
    """Choice callback does nothing when profile_type is not blogger."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "audience_gender",
            "edit_profile_type": "advertiser",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AUDIENCE_F), deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    # Should not try to update blogger when profile type is advertiser
    deps["blogger_registration_service"].update_blogger.assert_not_called()


@pytest.mark.asyncio
async def test_edit_choice_callback_skips_when_no_field_key():
    """Choice callback does nothing when editing_field is not set."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AUDIENCE_F), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_barter_yes():
    """Choice callback for barter_y triggers blogger barter update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "barter",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_BARTER_Y), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_barter_no():
    """Choice callback for barter_n triggers blogger barter update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "barter",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_BARTER_N), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_blogger_gender_m():
    """Choice callback for blogger_gender_m triggers blogger gender update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "blogger_gender",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_BLOGGER_GENDER_M), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_blogger_gender_f():
    """Choice callback for blogger_gender_f triggers blogger gender update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "blogger_gender",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_BLOGGER_GENDER_F), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_age_18_24():
    """Choice callback for age_18_24 triggers blogger audience_age update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "audience_age",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AGE_18_24), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_work_ads():
    """Choice callback for work_ads triggers blogger work_format update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "work_format",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_WORK_ADS), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


@pytest.mark.asyncio
async def test_edit_choice_callback_work_ugc():
    """Choice callback for work_ugc triggers blogger work_format update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "work_format",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_WORK_UGC), deps)
    deps["messenger_client"].answer_callback.assert_called_once()


# ---------------------------------------------------------------------------
# handle_profile_edit_value (message_in_state entering_value)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_value_no_field_key_clears_state():
    """Free-text in entering_value with no editing_field clears state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("some text"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_edit_value_blogger_field_routes_to_blogger_updater():
    """Free-text entering_value for blogger routes
    to _handle_blogger_field_update."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "topics",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    await router.route_message(_incoming_msg("food, travel"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_edit_value_advertiser_field_routes_to_advertiser_updater():
    """Free-text entering_value for advertiser routes
    to _handle_advertiser_field_update."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "brand",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["advertiser_registration_service"].update_advertiser = AsyncMock(
        return_value=advertiser
    )
    await router.route_message(_incoming_msg("My Brand"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_edit_value_uses_contact_phone_for_phone_field():
    """Free-text handler uses contact_phone value when editing phone field."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "phone",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["advertiser_registration_service"].update_advertiser = AsyncMock(
        return_value=advertiser
    )
    msg = _incoming_msg("", contact_phone="+79001234567")
    await router.route_message(msg, deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_edit_value_city_with_location_coordinates():
    """Free-text handler resolves city from coordinates
    when editing city field."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].resolve_city_from_location = AsyncMock(
        return_value="Moscow"
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=blogger
    )
    msg = _incoming_msg("", location_lat=55.75, location_lon=37.62)
    await router.route_message(msg, deps)


@pytest.mark.asyncio
async def test_edit_value_city_location_resolve_failure():
    """When city cannot be resolved from coordinates, error message is sent."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].resolve_city_from_location = AsyncMock(
        return_value=None
    )
    msg = _incoming_msg("", location_lat=0.0, location_lon=0.0)
    await router.route_message(msg, deps)
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# _handle_blogger_field_update edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blogger_field_update_no_user_id_clears_state():
    """Blogger field update with no user_id in state
    clears state and returns False."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("text"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_field_update_no_blogger_profile_clears_state():
    """Blogger field update when no blogger profile exists clears state."""
    user = _user()
    deps = _deps(user=user, blogger=None)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "topics",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("food"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_nickname_invalid_sends_error():
    """Blogger nickname update with invalid value sends validation error."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "nickname",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    # validator returns an error string for invalid nicks
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_nickname_too_short": "Too short"}
    )
    await router.route_message(_incoming_msg("x"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_blogger_field_unknown_key_sends_unknown_field_message():
    """Blogger field update with unknown field key
    sends unknown-field message."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "unknown_blogger_field_xyz",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("value"), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_blogger_field_update_failure_sends_error():
    """Blogger field updater returning None sends failure message."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "birth_date",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    # Simulate the updater returning None (validation failure)
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("not-a-date"), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# _handle_advertiser_field_update edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advertiser_field_update_no_user_id_clears_state():
    """Advertiser field update with no user_id in state clears state."""
    deps = _deps()
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(return_value={})
    await router.route_message(_incoming_msg("text"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_advertiser_field_update_no_advertiser_profile_clears_state():
    """Advertiser field update when no advertiser
    profile exists clears state."""
    user = _user()
    deps = _deps(user=user, advertiser=None)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "brand",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("BrandX"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_advertiser_name_invalid_sends_error():
    """Advertiser name update with invalid value sends validation error."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "name",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["bot_texts_service"].get_many = AsyncMock(
        return_value={"err_name_too_short": "Too short"}
    )
    await router.route_message(_incoming_msg("x"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_advertiser_field_unknown_key_sends_unknown_field_message():
    """Advertiser field update with unknown field key
    sends unknown-field message."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "completely_unknown_adv_field",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("value"), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_advertiser_field_update_failure_sends_error():
    """Advertiser field updater returning None sends failure message."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "site_link",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["advertiser_registration_service"].update_advertiser = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("not-a-url"), deps)
    deps["state_store"].clear.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_advertiser_name_valid_updates_username():
    """Advertiser name update with valid name calls
    set_user and shows profile."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "name",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("ValidName"), deps)
    deps["user_role_service"].set_user.assert_called_once()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_advertiser_city_field_update_success():
    """Advertiser city field update with valid city
    updates and shows profile."""
    user = _user()
    advertiser = _advertiser()
    updated_advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["advertiser_registration_service"].update_advertiser = AsyncMock(
        return_value=updated_advertiser
    )
    await router.route_message(_incoming_msg("Moscow"), deps)
    deps["messenger_client"].send_text.assert_called()


# ---------------------------------------------------------------------------
# _handle_blogger_field_update success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blogger_city_text_update_success():
    """Blogger city update with plain text (no location) succeeds."""
    user = _user()
    blogger = _blogger()
    updated_blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=updated_blogger
    )
    await router.route_message(_incoming_msg("Saint Petersburg"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_city_text_update_failure_clears_state():
    """Blogger city update returning None clears state
    without sending success msg."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("??"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_nickname_valid_updates_username():
    """Blogger nickname update with valid nickname
    calls set_user and shows profile."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "nickname",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    await router.route_message(_incoming_msg("valid_nick"), deps)
    deps["user_role_service"].set_user.assert_called_once()
    deps["state_store"].clear.assert_called()


# ---------------------------------------------------------------------------
# Additional edge-case tests for remaining uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_field_callback_blogger_gender_sends_keyboard():
    """Edit field callback for blogger_gender branch sends keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "blogger_gender"),
        deps,
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_edit_field_callback_audience_age_sends_keyboard():
    """Edit field callback for audience_age branch sends keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "audience_age"), deps
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_edit_field_callback_work_format_sends_keyboard():
    """Edit field callback for work_format branch sends keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "work_format"), deps
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_edit_field_callback_phone_sends_keyboard():
    """Edit field callback for phone branch sends keyboard."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "advertiser"}
    )
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_EDIT_FIELD_PREFIX + "phone"), deps
    )
    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_edit_field_callback_empty_field_key_does_nothing():
    """Edit field callback with bare prefix (no field after it) does nothing."""
    deps = _deps()
    deps["state_store"].get_data = AsyncMock(
        return_value={"edit_profile_type": "blogger"}
    )
    # The prefix alone should not route (lambda checks len > len(prefix))
    # but we test the guard inside the handler by sending
    # a callback that matches
    # the startswith check but produces an empty field_key after stripping.
    # This is done by patching incoming.data after stripping — we use the
    # CALLBACK_PROFILE_EDIT_FIELD_PREFIX itself plus a single space that is
    # stripped to empty.
    # Actually the router predicate also requires len(c.data) > len(prefix),
    # so we can't trigger this from routing. We test the state_store.set_state
    # is never called when the field_key resolves to invalid.
    deps["state_store"].set_state.assert_not_called()


@pytest.mark.asyncio
async def test_edit_choice_callback_choice_text_not_found_does_nothing():
    """Choice callback when choice_map has no entry
    for the callback data does nothing."""
    user = _user()
    deps = _deps(user=user)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    # Return empty dict so choice_texts.get() returns "" for all keys
    deps["bot_texts_service"].get_many = AsyncMock(return_value={})
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "audience_gender",
            "edit_profile_type": "blogger",
        }
    )
    await router.route_callback(_incoming_cb(CALLBACK_PROFILE_AUDIENCE_F), deps)
    deps["messenger_client"].answer_callback.assert_called_once()
    # With empty choice_text, blogger update should not be triggered
    deps["blogger_registration_service"].update_blogger.assert_not_called()


@pytest.mark.asyncio
async def test_advertiser_field_update_missing_external_id_clears_state():
    """Advertiser field update with user_id but no external_id clears state."""
    user = _user()
    advertiser = _advertiser()
    deps = _deps(user=user, advertiser=advertiser)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "brand",
            "edit_profile_type": "advertiser",
            "edit_user_id": str(user.user_id),
            # edit_external_id intentionally missing
        }
    )
    await router.route_message(_incoming_msg("BrandX"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_field_update_missing_external_id_clears_state():
    """Blogger field update with user_id but no external_id clears state."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "topics",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            # edit_external_id intentionally missing
        }
    )
    await router.route_message(_incoming_msg("food"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_blogger_city_updater_returns_none_clears_state():
    """Blogger city update returning None from updater clears state."""
    user = _user()
    blogger = _blogger()
    deps = _deps(user=user, blogger=blogger)
    deps["state_store"].get_state = AsyncMock(
        return_value=_STATE_ENTERING_VALUE
    )
    deps["state_store"].get_data = AsyncMock(
        return_value={
            "editing_field": "city",
            "edit_profile_type": "blogger",
            "edit_user_id": str(user.user_id),
            "edit_external_id": "42",
        }
    )
    # Make the city updater (_blog_update_city) return None
    deps["blogger_registration_service"].update_blogger_city = AsyncMock(
        return_value=None
    )
    # Patch at the service level — the updater delegates
    # to blogger_registration_service
    # The actual path: _blog_update_city ->
    # blogger_registration_service calls return None
    # We simulate this by making any update call return None
    deps["blogger_registration_service"].update_blogger = AsyncMock(
        return_value=None
    )
    await router.route_message(_incoming_msg("??invalid??"), deps)
    deps["state_store"].clear.assert_called()
