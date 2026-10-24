"""Real menu actions launch the signed partner screen with native buttons."""

import importlib
from types import SimpleNamespace

import pytest

from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.max.client import _build_inline_keyboard
from ugc_bot.infrastructure.messenger.telegram.client import (
    build_keyboard_markup,
)


def config():
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "MAX_BOT_TOKEN": "test-token",
            "WEBHOOK_BASE_URL": "https://tg.example.test",
            "MAX_BOT_WEBHOOK_URL": "https://max.example.test/max/webhook",
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,label",
    [
        ("ru", "Партнёрская программа"),
        ("en", "Partner program"),
        ("kk", "Серіктестік бағдарлама"),
        ("be", "Партнёрская праграма"),
        ("uz", "Hamkorlik dasturi"),
    ],
)
async def test_partner_command_uses_real_platform_shell_and_native_markup(
    platform, locale, label
):
    module = importlib.import_module(f"ugc_bot.bot.{platform}.handlers.start")
    handler = getattr(module, "partner_command", None)
    assert handler is not None, "Partner entry handler is missing"
    messenger = FakeMessengerClient()
    if platform == "telegram":
        incoming = SimpleNamespace(chat_id="101")
        adapter = SimpleNamespace(from_message=lambda _: incoming)
        await handler(
            object(),
            config(),
            user_locale=locale,
            messenger_client=messenger,
            event_adapter=adapter,
        )
    else:
        await handler(
            SimpleNamespace(chat_id="101"),
            {
                "config": config(),
                "messenger_client": messenger,
                "locale": locale,
            },
        )
    assert len(messenger.sent_text) == 1
    request = messenger.sent_text[0]
    button = request["keyboard"].rows[0][0]
    expected = (
        "https://tg.example.test/miniapp/app.html"
        if platform == "telegram"
        else "https://max.example.test/miniapp/max_app.html"
    ) + "?view=partner"
    assert button.text == label and button.web_app_url == expected
    if platform == "telegram":
        assert (
            build_keyboard_markup(request["keyboard"])
            .inline_keyboard[0][0]
            .web_app.url
            == expected
        )
    else:
        assert _build_inline_keyboard(request["keyboard"])["payload"][
            "buttons"
        ][0][0] == {"type": "open_app", "text": label, "web_app": expected}


@pytest.mark.parametrize(
    "builder",
    [
        "role_inline_keyboard",
        "main_menu_inline_keyboard",
        "creator_filled_profile_inline_keyboard",
        "advertiser_menu_inline_keyboard",
    ],
)
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_existing_role_menus_expose_localized_partner_callback(builder, locale):
    module = importlib.import_module("ugc_bot.bot.telegram.handlers.keyboards")
    texts = DEFAULT_TEXTS[locale]
    keyboard = getattr(module, builder)(texts)
    buttons = [
        button
        for row in keyboard.rows
        for button in row
        if button.callback_data == "partner:open"
    ]
    assert len(buttons) == 1
    assert buttons[0].text == texts["btn_partner_program"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_partner_menu_callback_is_answered_and_opens_own_native_screen(
    platform,
):
    module = importlib.import_module(f"ugc_bot.bot.{platform}.handlers.start")
    messenger = FakeMessengerClient()
    incoming = SimpleNamespace(chat_id="101", callback_id="callback-1")
    if platform == "telegram":
        await module.partner_callback(
            object(),
            config(),
            user_locale="en",
            messenger_client=messenger,
            event_adapter=SimpleNamespace(from_callback=lambda _: incoming),
        )
    else:
        await module.partner_callback(
            incoming,
            {"config": config(), "messenger_client": messenger, "locale": "en"},
        )
    assert len(messenger.answered_callbacks) == 1
    assert (
        messenger.sent_text[0]["keyboard"]
        .rows[0][0]
        .web_app_url.endswith("?view=partner")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_missing_shell_url_reports_unavailable_without_fake_button(
    platform,
):
    from ugc_bot.bot.partner_entry import send_partner_entry

    messenger = FakeMessengerClient()
    await send_partner_entry(
        messenger,
        "101",
        AppConfig.model_validate({"BOT_TOKEN": "test-token"}),
        platform,
        "en",
    )
    assert messenger.sent_text[0]["keyboard"] is None
    assert "unavailable" in messenger.sent_text[0]["text"]


@pytest.mark.asyncio
async def test_malformed_configured_url_never_creates_a_native_button():
    from ugc_bot.bot.partner_entry import send_partner_entry

    messenger = FakeMessengerClient()
    malformed = SimpleNamespace(
        webhook=SimpleNamespace(webhook_base_url="https://[")
    )
    await send_partner_entry(messenger, "101", malformed, "telegram", "en")
    assert messenger.sent_text[0]["keyboard"] is None
    assert "unavailable" in messenger.sent_text[0]["text"]
