from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.bot.customer_actions import show_services
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.max.client import _build_inline_keyboard


@pytest.mark.asyncio
async def test_max_services_button_uses_bot_identity_and_launch_payload():
    messenger = SimpleNamespace(send_text=AsyncMock())
    config = SimpleNamespace(
        webhook=SimpleNamespace(webhook_base_url="https://bot.example"),
        referral=SimpleNamespace(max_referral_bot_username="example_bot"),
    )
    await show_services(
        IncomingMessage("12", IncomingUser("12", MessengerType.MAX)),
        messenger,
        config,
    )
    keyboard = messenger.send_text.await_args.kwargs["keyboard"]
    button = _build_inline_keyboard(keyboard)["payload"]["buttons"][0][0]
    assert button["type"] == "open_app"
    assert button["web_app"] == "example_bot"
    assert button["payload"] == "services"


@pytest.mark.asyncio
async def test_max_services_without_bot_username_does_not_send_invalid_button():
    messenger = SimpleNamespace(send_text=AsyncMock())
    config = SimpleNamespace(
        webhook=SimpleNamespace(webhook_base_url="https://bot.example"),
        referral=SimpleNamespace(max_referral_bot_username=""),
    )
    await show_services(
        IncomingMessage("12", IncomingUser("12", MessengerType.MAX)),
        messenger,
        config,
    )
    assert messenger.send_text.await_args.kwargs["keyboard"] is None
