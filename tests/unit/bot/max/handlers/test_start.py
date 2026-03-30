"""Tests for Max start and role selection handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.start import router
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_CHANGE_COUNTRY_PREFIX,
    CALLBACK_CHANGE_ROLE,
    CALLBACK_COUNTRY_PREFIX,
    CALLBACK_LANG_PREFIX,
    CALLBACK_SUPPORT,
)
from ugc_bot.domain.enums import MessengerType


def _user(*, country=None, language="ru"):
    u = MagicMock()
    u.user_id = "u1"
    u.username = "alice"
    u.country = country
    u.language = language
    u.referral_code = ""
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


def _deps(*, user=None, start_text="", support_response="", support_chat_id=""):
    mock_config = MagicMock()
    mock_config.market.default_locale = "ru"
    mock_config.market.start_text = start_text
    mock_config.market.support_response_text = ""
    mock_config.market.support_chat_id = support_chat_id
    mock_config.max_bot = MagicMock(webhook_url="https://example.com/webhook")

    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)
    user_role_service.get_user_by_id = AsyncMock(return_value=user)
    user_role_service.set_country = AsyncMock(return_value=user)
    user_role_service.set_language = AsyncMock(return_value=user)

    # Provide the text keys that role_inline_keyboard and other keyboards need
    _texts = {
        "btn_creator": "Creator",
        "btn_advertiser": "Advertiser",
        "btn_support": "Support",
        "btn_support_write": "Write",
        "btn_change_role": "Change role",
        "start_message": start_text,
        "country_prompt": "Choose country:",
        "language_prompt": "Choose language:",
        "country_changed": "Country changed.",
    }

    async def _get(key, locale="ru"):
        return _texts.get(key, support_response if "support" in key else "")

    async def _get_many(keys, locale="ru"):
        return {k: _texts.get(k, "") for k in keys}

    return {
        "messenger_client": AsyncMock(),
        "user_role_service": user_role_service,
        "referral_service": AsyncMock(),
        "bot_texts_service": AsyncMock(
            get=AsyncMock(side_effect=_get),
            get_many=AsyncMock(side_effect=_get_many),
        ),
        "state_store": AsyncMock(),
        "config": mock_config,
        "country_repo": None,
        "language_repo": None,
        "locale": "ru",
    }


# ── /start ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_handler_sends_welcome():
    """/start sends welcome message."""
    deps = _deps()
    await router.route_message(_incoming_msg("/start"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_start_handler_sets_country_ru():
    """/start always sets country to RU for Max users."""
    deps = _deps()
    await router.route_message(_incoming_msg("/start"), deps)
    deps["user_role_service"].set_country.assert_called_once()
    call_kwargs = deps["user_role_service"].set_country.call_args.kwargs
    assert call_kwargs["country_code"] == "ru"


@pytest.mark.asyncio
async def test_start_handler_uses_fallback_text_when_empty():
    """/start uses fallback text when start_text is empty."""
    deps = _deps(start_text="")
    await router.route_message(_incoming_msg("/start"), deps)
    deps["messenger_client"].send_text.assert_called()
    text = deps["messenger_client"].send_text.call_args.kwargs["text"]
    assert len(text) > 0


@pytest.mark.asyncio
async def test_start_handler_with_referral_code():
    """/start ref_CODE is handled the same as /start."""
    deps = _deps()
    await router.route_message(_incoming_msg("/start ref_ABC123"), deps)
    deps["messenger_client"].send_text.assert_called()
    deps["user_role_service"].set_country.assert_called_once()


# ── country_selected callback ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_country_selected_saves_country_and_shows_role_kb():
    """country: callback saves country and shows role keyboard."""
    user = _user(country=None)
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_COUNTRY_PREFIX}ru"), deps
    )
    deps["user_role_service"].set_country.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_country_selected_skips_when_user_already_has_country():
    """country: callback is no-op when user already has a country set."""
    user = _user(country="RU")
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_COUNTRY_PREFIX}ru"), deps
    )
    deps["user_role_service"].set_country.assert_not_called()


@pytest.mark.asyncio
async def test_country_selected_empty_code_returns_early():
    """country: callback with empty country code returns early."""
    user = _user(country=None)
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(CALLBACK_COUNTRY_PREFIX), deps)
    deps["user_role_service"].set_country.assert_not_called()


@pytest.mark.asyncio
async def test_country_selected_validates_via_country_repo():
    """country: callback validates code via country_repo when provided."""
    user = _user(country=None)
    deps = _deps(user=user)
    country_repo = AsyncMock()
    country_repo.get_by_code = AsyncMock(return_value=None)
    deps["country_repo"] = country_repo
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_COUNTRY_PREFIX}xx"), deps
    )
    # Unknown country → returns early without setting
    deps["user_role_service"].set_country.assert_not_called()


# ── language_selected callback ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_language_selected_saves_language_and_shows_role_kb():
    """lang: callback saves language and shows role keyboard."""
    user = _user(country="RU")
    deps = _deps(user=user)
    await router.route_callback(_incoming_cb(f"{CALLBACK_LANG_PREFIX}ru"), deps)
    deps["user_role_service"].set_language.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_language_selected_empty_code_returns_early():
    """lang: callback with empty code returns early."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(CALLBACK_LANG_PREFIX), deps)
    deps["user_role_service"].set_language.assert_not_called()


@pytest.mark.asyncio
async def test_language_selected_user_not_found_returns_early():
    """lang: callback with UserNotFoundError returns early."""
    deps = _deps(user=_user())
    deps["user_role_service"].set_language = AsyncMock(
        side_effect=UserNotFoundError("not found")
    )
    await router.route_callback(_incoming_cb(f"{CALLBACK_LANG_PREFIX}ru"), deps)
    deps["messenger_client"].send_text.assert_not_called()


@pytest.mark.asyncio
async def test_language_selected_no_country_shows_country_keyboard():
    """lang: callback when user has no country shows country keyboard."""
    user = _user(country=None)
    deps = _deps(user=user)
    country_repo = AsyncMock()
    country_repo.list_enabled = AsyncMock(return_value=[])
    deps["country_repo"] = country_repo
    deps["user_role_service"].set_language = AsyncMock(return_value=user)
    await router.route_callback(_incoming_cb(f"{CALLBACK_LANG_PREFIX}en"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_language_selected_validates_via_language_repo():
    """lang: callback validates code via language_repo when provided."""
    deps = _deps(user=_user())
    language_repo = AsyncMock()
    language_repo.get_by_code = AsyncMock(return_value=None)
    deps["language_repo"] = language_repo
    await router.route_callback(_incoming_cb(f"{CALLBACK_LANG_PREFIX}xx"), deps)
    deps["user_role_service"].set_language.assert_not_called()


# ── /language command ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_language_command_sends_keyboard():
    """/language sends language selection keyboard."""
    deps = _deps(user=_user())
    await router.route_message(_incoming_msg("/language"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_language_command_uses_language_repo_when_available():
    """/language lists languages via language_repo."""
    deps = _deps(user=_user())
    language_repo = AsyncMock()
    language_repo.list_enabled = AsyncMock(return_value=[])
    deps["language_repo"] = language_repo
    await router.route_message(_incoming_msg("/language"), deps)
    language_repo.list_enabled.assert_called_once()


# ── /country command ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_country_command_sends_keyboard():
    """/country sends country selection keyboard."""
    deps = _deps(user=_user())
    await router.route_message(_incoming_msg("/country"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_country_command_uses_country_repo_when_available():
    """/country lists countries via country_repo."""
    deps = _deps(user=_user())
    country_repo = AsyncMock()
    country_repo.list_enabled = AsyncMock(return_value=[])
    deps["country_repo"] = country_repo
    await router.route_message(_incoming_msg("/country"), deps)
    country_repo.list_enabled.assert_called_once()


# ── chg_country: callback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_country_change_selected_saves_country():
    """chg_country: callback saves the new country."""
    user = _user(country=None)
    deps = _deps(user=user)
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_CHANGE_COUNTRY_PREFIX}ru"), deps
    )
    deps["user_role_service"].set_country.assert_called_once()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_country_change_selected_empty_code_returns_early():
    """chg_country: callback with empty code returns early."""
    deps = _deps(user=_user())
    await router.route_callback(
        _incoming_cb(CALLBACK_CHANGE_COUNTRY_PREFIX), deps
    )
    deps["user_role_service"].set_country.assert_not_called()


@pytest.mark.asyncio
async def test_country_change_selected_user_not_found_returns_early():
    """chg_country: UserNotFoundError returns early."""
    deps = _deps(user=_user())
    deps["user_role_service"].set_country = AsyncMock(
        side_effect=UserNotFoundError("not found")
    )
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_CHANGE_COUNTRY_PREFIX}ru"), deps
    )
    deps["messenger_client"].send_text.assert_not_called()


@pytest.mark.asyncio
async def test_country_change_validates_via_country_repo():
    """chg_country: validates code via country_repo when provided."""
    deps = _deps(user=_user())
    country_repo = AsyncMock()
    country_repo.get_by_code = AsyncMock(return_value=None)
    deps["country_repo"] = country_repo
    await router.route_callback(
        _incoming_cb(f"{CALLBACK_CHANGE_COUNTRY_PREFIX}xx"), deps
    )
    deps["user_role_service"].set_country.assert_not_called()


# ── change_role callback ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_change_role_callback_shows_start_screen():
    """change_role callback shows start screen."""
    deps = _deps(user=_user())
    await router.route_callback(_incoming_cb(CALLBACK_CHANGE_ROLE), deps)
    deps["messenger_client"].answer_callback.assert_called()


# ── /role command ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_role_command_sends_welcome():
    """/role command sends start screen."""
    deps = _deps(user=_user())
    await router.route_message(_incoming_msg("/role"), deps)
    deps["messenger_client"].send_text.assert_called()


# ── /app command ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_app_command_sends_miniapp_button():
    """/app sends miniapp open button."""
    deps = _deps()
    await router.route_message(_incoming_msg("/app"), deps)
    deps["messenger_client"].send_text.assert_called()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs.get("keyboard") is not None


@pytest.mark.asyncio
async def test_app_command_no_webhook_url_sends_unavailable():
    """/app with no webhook_url sends unavailable text."""
    deps = _deps()
    deps["config"].max_bot.webhook_url = ""
    await router.route_message(_incoming_msg("/app"), deps)
    deps["messenger_client"].send_text.assert_called()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert "недоступен" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_app_command_no_max_bot_config_sends_unavailable():
    """/app with max_bot=None sends unavailable text."""
    deps = _deps()
    deps["config"].max_bot = None
    await router.route_message(_incoming_msg("/app"), deps)
    deps["messenger_client"].send_text.assert_called()
    text = deps["messenger_client"].send_text.call_args.kwargs["text"]
    assert "недоступен" in text


# ── support_callback ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_support_callback_sends_support_text():
    """support callback sends support text."""
    deps = _deps(support_response="Служба поддержки!")
    await router.route_callback(_incoming_cb(CALLBACK_SUPPORT), deps)
    deps["messenger_client"].answer_callback.assert_called()
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_support_callback_uses_fallback_when_empty():
    """support callback uses fallback text when service returns empty."""
    deps = _deps(support_response="")
    await router.route_callback(_incoming_cb(CALLBACK_SUPPORT), deps)
    deps["messenger_client"].send_text.assert_called()
    text = deps["messenger_client"].send_text.call_args.kwargs["text"]
    assert len(text) > 0


@pytest.mark.asyncio
async def test_support_callback_includes_write_button_when_chat_configured():
    """support callback includes 'Write to support' button when chat_id set."""
    deps = _deps(support_chat_id="12345")
    await router.route_callback(_incoming_cb(CALLBACK_SUPPORT), deps)
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    keyboard = call_kwargs.get("keyboard")
    assert keyboard is not None
    all_callbacks = [btn.callback_data for row in keyboard.rows for btn in row]
    # Should contain change_role button at minimum
    assert CALLBACK_CHANGE_ROLE in all_callbacks


@pytest.mark.asyncio
async def test_support_callback_clears_state():
    """support callback clears FSM state."""
    deps = _deps()
    await router.route_callback(_incoming_cb(CALLBACK_SUPPORT), deps)
    deps["state_store"].clear.assert_called()


# ── /support command ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_support_command_sends_support_text():
    """/support command sends support text."""
    deps = _deps(support_response="Поддержка доступна.")
    await router.route_message(_incoming_msg("/support"), deps)
    deps["messenger_client"].send_text.assert_called()


@pytest.mark.asyncio
async def test_support_command_uses_fallback_when_empty():
    """/support uses fallback text when all sources empty."""
    deps = _deps(support_response="")
    deps["config"].market.support_response_text = ""
    await router.route_message(_incoming_msg("/support"), deps)
    text = deps["messenger_client"].send_text.call_args.kwargs["text"]
    assert len(text) > 0


@pytest.mark.asyncio
async def test_support_command_clears_state():
    """/support clears FSM state."""
    deps = _deps()
    await router.route_message(_incoming_msg("/support"), deps)
    deps["state_store"].clear.assert_called()


@pytest.mark.asyncio
async def test_support_command_falls_back_to_market_support_response():
    """/support falls back to market.support_response_text when empty."""
    deps = _deps(support_response="")
    deps["config"].market.support_response_text = "Напишите нам"
    await router.route_message(_incoming_msg("/support"), deps)
    text = deps["messenger_client"].send_text.call_args.kwargs["text"]
    assert "Напишите нам" in text
