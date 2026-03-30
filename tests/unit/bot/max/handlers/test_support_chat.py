"""Tests for Max support chat handlers."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.max.handlers.support_chat import (
    CALLBACK_SUPPORT_EXIT,
    CALLBACK_SUPPORT_START_CHAT,
    SUPPORT_STATE,
    router,
)
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def _config():
    cfg = MagicMock()
    cfg.market.default_locale = "ru"
    cfg.market.support_chat_id = "-100123456"
    return cfg


@pytest.fixture
def _config_no_chat():
    cfg = MagicMock()
    cfg.market.default_locale = "ru"
    cfg.market.support_chat_id = ""
    return cfg


@pytest.fixture
def deps(_config):
    mock_user = AsyncMock(
        language="ru", username="alice", user_id=uuid4(), telegram="alice_tg"
    )
    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=mock_user)

    mock_profile = AsyncMock(
        phone="+79991234567", instagram_url="https://instagram.com/alice"
    )
    profile_service = AsyncMock()
    profile_service.get_blogger_profile = AsyncMock(return_value=mock_profile)

    bot_texts_service = AsyncMock()
    bot_texts_service.get = AsyncMock(return_value="")
    bot_texts_service.get_many = AsyncMock(return_value={})

    # Telegram bot mock for forwarding
    sent_message = MagicMock()
    sent_message.message_id = 999
    telegram_bot = AsyncMock()
    telegram_bot.send_message = AsyncMock(return_value=sent_message)
    telegram_client = MagicMock()
    telegram_client._bot = telegram_bot

    return {
        "messenger_client": AsyncMock(),
        "telegram_messenger_client": telegram_client,
        "user_role_service": user_role_service,
        "bot_texts_service": bot_texts_service,
        "profile_service": profile_service,
        "support_service": AsyncMock(),
        "state_store": AsyncMock(),
        "config": _config,
    }


def _make_callback(data: str) -> IncomingCallback:
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="100",
        user=IncomingUser(
            external_id="42", messenger_type=MessengerType.MAX, username="alice"
        ),
        data=data,
        message_id="msg_1",
    )


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42", messenger_type=MessengerType.MAX, username="alice"
        ),
        text=text,
        message_id="msg_2",
    )


@pytest.mark.asyncio
async def test_start_support_chat_sets_state(deps):
    incoming = _make_callback(CALLBACK_SUPPORT_START_CHAT)
    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_called_once_with(SUPPORT_STATE)
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_start_support_chat_not_configured(deps, _config_no_chat):
    deps["config"] = _config_no_chat
    incoming = _make_callback(CALLBACK_SUPPORT_START_CHAT)
    await router.route_callback(incoming, deps)

    deps["state_store"].set_state.assert_not_called()
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_user_message_forwards(deps):
    deps["state_store"].get_state = AsyncMock(return_value=SUPPORT_STATE)
    incoming = _make_message("Hello support!")
    await router.route_message(incoming, deps)

    # Should forward to Telegram group
    telegram_bot = deps["telegram_messenger_client"]._bot
    telegram_bot.send_message.assert_called_once()
    call_kwargs = telegram_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == -100123456
    assert "Hello support!" in call_kwargs["text"]

    # Should record the mapping
    deps["support_service"].record_forwarded_message.assert_called_once_with(
        user_chat_id="100",
        support_chat_message_id=999,
        user_text="Hello support!",
    )

    # Should confirm to user
    deps["messenger_client"].send_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_user_message_empty_text(deps):
    deps["state_store"].get_state = AsyncMock(return_value=SUPPORT_STATE)
    incoming = _make_message("")
    await router.route_message(incoming, deps)

    deps["telegram_messenger_client"]._bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_user_message_not_configured(deps, _config_no_chat):
    deps["config"] = _config_no_chat
    deps["state_store"].get_state = AsyncMock(return_value=SUPPORT_STATE)
    incoming = _make_message("Hello!")
    await router.route_message(incoming, deps)

    deps["telegram_messenger_client"]._bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_exit_support_chat(deps):
    deps["state_store"].get_state = AsyncMock(return_value=SUPPORT_STATE)
    incoming = _make_callback(CALLBACK_SUPPORT_EXIT)
    await router.route_callback(incoming, deps)

    deps["state_store"].clear.assert_called_once()
    deps["messenger_client"].send_text.assert_called_once()
