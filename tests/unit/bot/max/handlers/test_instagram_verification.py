"""Tests for Max Instagram verification handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.instagram_verification import router
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


def _user(*, status=UserStatus.ACTIVE):
    u = MagicMock()
    u.user_id = uuid4()
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


def _deps(
    user=None, *, blogger_profile=None, admin_instagram_username="admin_test"
):
    mock_config = MagicMock()
    mock_config.market.default_locale = "ru"
    mock_config.instagram.admin_instagram_username = admin_instagram_username

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    profile_service = AsyncMock()
    profile_service.get_blogger_profile = AsyncMock(
        return_value=blogger_profile
    )

    verification = MagicMock()
    verification.code = "ABC123"
    instagram_verification_service = AsyncMock()
    instagram_verification_service.generate_code = AsyncMock(
        return_value=verification,
    )

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "profile_service": profile_service,
        "instagram_verification_service": instagram_verification_service,
        "bot_texts_service": AsyncMock(
            get=AsyncMock(return_value=""),
            get_many=AsyncMock(return_value={}),
        ),
        "state_store": AsyncMock(),
        "config": mock_config,
        "locale": "ru",
    }


# ── /verify_instagram command ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_instagram_user_not_found():
    """/verify_instagram with no user sends error."""
    deps = _deps(user=None)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_blocked_user():
    """Blocked user gets blocked message."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_pause_user():
    """Paused user gets pause message."""
    user = _user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_no_profile():
    """User without blogger profile gets empty-profile message."""
    user = _user()
    deps = _deps(user=user, blogger_profile=None)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_already_confirmed():
    """Already confirmed user gets already-confirmed message."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_sends_code():
    """Valid user gets verification code sent."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["instagram_verification_service"].generate_code.assert_called_once()
    # Two messages: instruction + code with keyboard
    assert deps["messenger_client"].send_text.call_count == 2


@pytest.mark.asyncio
async def test_verify_instagram_sends_code_html_escaped():
    """Verification code message uses parse_mode=HTML."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    # Second call should have parse_mode=HTML
    second_call_kwargs = (
        deps["messenger_client"].send_text.call_args_list[1].kwargs
    )
    assert second_call_kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_verify_instagram_clears_state():
    """/verify_instagram clears FSM state before sending code."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    deps["state_store"].clear.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_instagram_alias():
    """/confirm_instagram alias also triggers verification."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_message(_incoming_msg("/confirm_instagram"), deps)
    deps["instagram_verification_service"].generate_code.assert_called_once()


@pytest.mark.asyncio
async def test_verify_instagram_without_admin_username():
    """Verification works even if admin_instagram_username is empty."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(
        user=user, blogger_profile=profile, admin_instagram_username=""
    )
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    assert deps["messenger_client"].send_text.call_count == 2


@pytest.mark.asyncio
async def test_verify_instagram_code_sent_without_keyboard_when_no_admin():
    """Second message still sent with keyboard even when no admin DM URL."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(
        user=user, blogger_profile=profile, admin_instagram_username=""
    )
    await router.route_message(_incoming_msg("/verify_instagram"), deps)
    # Both messages sent
    assert deps["messenger_client"].send_text.call_count == 2


# ── CALLBACK_PROFILE_CONFIRM_INSTAGRAM callback ───────────────────────────────


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_user_not_found():
    """Callback with no user sends error message."""
    deps = _deps(user=None)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_blocked_user():
    """Callback with blocked user sends blocked message."""
    user = _user(status=UserStatus.BLOCKED)
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_pause_user():
    """Callback with paused user sends pause message."""
    user = _user(status=UserStatus.PAUSE)
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_no_profile():
    """Callback with no blogger profile sends empty-profile message."""
    user = _user()
    deps = _deps(user=user, blogger_profile=None)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_already_confirmed():
    """Callback when instagram already confirmed sends already-confirmed."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = True
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["messenger_client"].answer_callback.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_sends_code():
    """Callback with valid unconfirmed profile generates and sends code."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["instagram_verification_service"].generate_code.assert_called_once()
    # answer_callback + 2 send_text (instruction + code)
    assert deps["messenger_client"].send_text.call_count == 2


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_code_uses_html():
    """Callback code message uses HTML parse mode."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    second_call_kwargs = (
        deps["messenger_client"].send_text.call_args_list[1].kwargs
    )
    assert second_call_kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_clears_state():
    """Callback clears FSM state before sending code."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)
    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    deps["state_store"].clear.assert_called_once()


@pytest.mark.asyncio
async def test_profile_confirm_instagram_callback_answers_first():
    """Callback always calls answer_callback before any send_text."""
    user = _user()
    profile = MagicMock()
    profile.confirmed = False
    deps = _deps(user=user, blogger_profile=profile)

    call_order = []
    deps["messenger_client"].answer_callback = AsyncMock(
        side_effect=lambda **kwargs: call_order.append("answer")
    )
    deps["messenger_client"].send_text = AsyncMock(
        side_effect=lambda **kwargs: call_order.append("send")
    )

    await router.route_callback(
        _incoming_cb(CALLBACK_PROFILE_CONFIRM_INSTAGRAM), deps
    )
    assert call_order[0] == "answer"
