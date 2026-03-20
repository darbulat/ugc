"""Tests for keyboard helpers (inline only)."""

from ugc_bot.application.messenger.dto import KeyboardKind
from ugc_bot.bot.handlers.keyboards import (
    MINIAPP_OPEN_BUTTON_TEXT,
    advertiser_menu_inline_keyboard,
    advertiser_start_keyboard,
    blogger_after_registration_inline_keyboard,
    blogger_menu_inline_keyboard,
    blogger_profile_view_inline_keyboard,
    blogger_verification_sent_inline_keyboard,
    creator_filled_profile_inline_keyboard,
    flow_keyboard_city_request,
    main_menu_inline_keyboard,
    miniapp_open_inline_keyboard,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

_TEXTS_RU = DEFAULT_TEXTS["ru"]


def test_blogger_menu_inline_keyboard_not_confirmed() -> None:
    """Show verification button when Instagram is not confirmed."""
    keyboard = blogger_menu_inline_keyboard(
        _TEXTS_RU, confirmed=False, verification_started=False
    )

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_confirm_instagram"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_menu_inline_keyboard_confirmed() -> None:
    """Hide verification button when Instagram is confirmed."""
    keyboard = blogger_menu_inline_keyboard(
        _TEXTS_RU, confirmed=True, verification_started=False
    )

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_my_profile"]


def test_main_menu_inline_keyboard() -> None:
    """Main menu has Support and Change role as inline buttons."""
    keyboard = main_menu_inline_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_support"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_change_role"]


def test_advertiser_start_keyboard() -> None:
    """Advertiser start keyboard has only Start before profile filled."""
    keyboard = advertiser_start_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_advertiser_start"]


def test_advertiser_menu_inline_keyboard() -> None:
    """Advertiser menu: Create order, My orders, Profile, Edit (inline)."""
    keyboard = advertiser_menu_inline_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 3
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_create_order"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_orders"]
    assert keyboard.rows[2][0].text == _TEXTS_RU["btn_my_profile"]
    assert keyboard.rows[2][1].text == _TEXTS_RU["btn_edit_profile"]


def test_creator_filled_profile_inline_keyboard() -> None:
    """Creator menu: Edit, My profile, My orders, Support (inline)."""
    keyboard = creator_filled_profile_inline_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert keyboard.rows is not None
    assert len(keyboard.rows) == 4
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_edit_profile"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_profile"]
    assert keyboard.rows[2][0].text == _TEXTS_RU["btn_my_orders"]
    assert keyboard.rows[3][0].text == _TEXTS_RU["btn_support"]


def test_blogger_profile_view_inline_keyboard_not_confirmed() -> None:
    """Blogger profile view: Edit, Confirm Instagram, My profile (inline)."""
    keyboard = blogger_profile_view_inline_keyboard(_TEXTS_RU, confirmed=False)

    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 3
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_edit_profile"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_confirm_instagram"]
    assert keyboard.rows[2][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_profile_view_inline_keyboard_confirmed() -> None:
    """Blogger profile view when confirmed: Edit, My profile (inline)."""
    keyboard = blogger_profile_view_inline_keyboard(_TEXTS_RU, confirmed=True)

    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_edit_profile"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_after_registration_inline_keyboard() -> None:
    """After blogger reg: Confirm Instagram, My profile (inline)."""
    keyboard = blogger_after_registration_inline_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_confirm_instagram"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_verification_sent_inline_keyboard() -> None:
    """After code sent: My profile only (inline)."""
    keyboard = blogger_verification_sent_inline_keyboard(_TEXTS_RU)

    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_my_profile"]


def test_flow_keyboard_city_request_without_miniapp_url() -> None:
    """City request keyboard has one row (location only) when no URL."""
    texts = {
        "btn_location_request": "Share location",
        "btn_location_map": "Map",
    }
    keyboard = flow_keyboard_city_request(texts)

    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].request_location is True
    assert keyboard.rows[0][0].web_app_url is None


def test_flow_keyboard_city_request_with_miniapp_url() -> None:
    """City request keyboard has two rows when miniapp URL provided."""
    texts = {"btn_location_request": "Share", "btn_location_map": "Pick on map"}
    keyboard = flow_keyboard_city_request(
        texts,
        miniapp_location_url="https://bot.example/miniapp/location_picker.html",
    )

    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].request_location is True
    assert keyboard.rows[1][0].web_app_url == (
        "https://bot.example/miniapp/location_picker.html"
    )
    assert keyboard.rows[1][0].text == "Pick on map"


def test_miniapp_open_inline_keyboard_with_url() -> None:
    """miniapp_open_inline_keyboard with URL returns one web_app button."""
    keyboard = miniapp_open_inline_keyboard("https://example.com")
    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 1
    assert len(keyboard.rows[0]) == 1
    assert keyboard.rows[0][0].text == MINIAPP_OPEN_BUTTON_TEXT
    assert (
        keyboard.rows[0][0].web_app_url
        == "https://example.com/miniapp/app.html"
    )


def test_miniapp_open_inline_keyboard_empty_url() -> None:
    """miniapp_open_inline_keyboard with empty URL returns no rows."""
    keyboard = miniapp_open_inline_keyboard("")
    assert keyboard.kind == KeyboardKind.INLINE
    assert len(keyboard.rows) == 0


def test_build_support_telegram_url_with_username() -> None:
    """build_support_telegram_url returns t.me URL for a valid username."""
    from ugc_bot.bot.handlers.keyboards import build_support_telegram_url

    assert (
        build_support_telegram_url("support_bot") == "https://t.me/support_bot"
    )
    assert (
        build_support_telegram_url("@support_bot") == "https://t.me/support_bot"
    )


def test_build_support_telegram_url_empty_returns_none() -> None:
    """build_support_telegram_url returns None for empty/whitespace input."""
    from ugc_bot.bot.handlers.keyboards import build_support_telegram_url

    assert build_support_telegram_url("") is None
    assert build_support_telegram_url("   ") is None


def test_keyboard_property_alias() -> None:
    """Keyboard.keyboard property is an alias for rows."""
    from ugc_bot.application.messenger.dto import Keyboard

    kb = Keyboard(kind=KeyboardKind.INLINE, rows=[])
    assert kb.keyboard is kb.rows
