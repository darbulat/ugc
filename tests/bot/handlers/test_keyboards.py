"""Tests for keyboard helpers."""

from ugc_bot.application.messenger.dto import KeyboardKind
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    CONFIRM_INSTAGRAM_BUTTON_TEXT,
    CREATE_ORDER_BUTTON_TEXT,
    MY_ORDERS_BUTTON_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    SUPPORT_BUTTON_TEXT,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    blogger_menu_keyboard,
    main_menu_keyboard,
    profile_keyboard,
    support_inline_keyboard,
    support_link_button,
)


def test_blogger_menu_keyboard_not_confirmed() -> None:
    """Show verification button when Instagram is not confirmed."""
    keyboard = blogger_menu_keyboard(confirmed=False)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == CONFIRM_INSTAGRAM_BUTTON_TEXT
    assert keyboard.rows[1][0].text == MY_PROFILE_BUTTON_TEXT


def test_blogger_menu_keyboard_confirmed() -> None:
    """Hide verification button when Instagram is confirmed."""
    keyboard = blogger_menu_keyboard(confirmed=True)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == MY_PROFILE_BUTTON_TEXT


def test_blogger_menu_keyboard_one_time() -> None:
    """Respect one_time_keyboard parameter."""
    keyboard = blogger_menu_keyboard(confirmed=False, one_time_keyboard=True)

    assert keyboard.one_time is True


def test_blogger_menu_keyboard_resize() -> None:
    """Keyboard should always be resizable."""
    keyboard = blogger_menu_keyboard(confirmed=False)

    assert keyboard.resize is True


def test_main_menu_keyboard_persistent() -> None:
    """Main menu has Support and Change role, is persistent."""
    keyboard = main_menu_keyboard()

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == SUPPORT_BUTTON_TEXT
    assert keyboard.rows[1][0].text == "Смена роли"
    assert keyboard.is_persistent is True
    assert keyboard.one_time is False


def test_advertiser_start_keyboard() -> None:
    """Advertiser start keyboard has only Начать before profile filled."""
    keyboard = advertiser_start_keyboard()

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == ADVERTISER_START_BUTTON_TEXT
    assert keyboard.rows[0][0].text == "Начать"


def test_advertiser_menu_keyboard() -> None:
    """Advertiser menu: Create order, My orders, My profile, Edit, Support."""
    from ugc_bot.bot.handlers.keyboards import EDIT_PROFILE_BUTTON_TEXT

    keyboard = advertiser_menu_keyboard()

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 5
    assert keyboard.rows[0][0].text == CREATE_ORDER_BUTTON_TEXT
    assert keyboard.rows[1][0].text == MY_ORDERS_BUTTON_TEXT
    assert keyboard.rows[2][0].text == MY_PROFILE_BUTTON_TEXT
    assert keyboard.rows[3][0].text == EDIT_PROFILE_BUTTON_TEXT
    assert keyboard.rows[4][0].text == SUPPORT_BUTTON_TEXT


def test_profile_keyboard() -> None:
    """Profile keyboard has single My profile button."""
    keyboard = profile_keyboard()

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == MY_PROFILE_BUTTON_TEXT
    assert keyboard.one_time is True


def test_profile_keyboard_one_time_false() -> None:
    """Profile keyboard respects one_time_keyboard=False."""
    keyboard = profile_keyboard(one_time_keyboard=False)

    assert keyboard.one_time is False


def test_support_link_button_returns_button_when_username_set() -> None:
    """support_link_button returns Button with SUPPORT_BUTTON_TEXT and URL."""
    btn = support_link_button("usemycontent")
    assert btn is not None
    assert btn.text == SUPPORT_BUTTON_TEXT
    assert btn.url == "https://t.me/usemycontent"


def test_support_link_button_strips_at_prefix() -> None:
    """support_link_button strips @ from username."""
    btn = support_link_button("@support_team")
    assert btn is not None
    assert btn.url == "https://t.me/support_team"


def test_support_link_button_returns_none_when_empty() -> None:
    """support_link_button returns None when username is empty."""
    assert support_link_button("") is None
    assert support_link_button("   ") is None


def test_support_inline_keyboard_returns_keyboard_when_username_set() -> None:
    """support_inline_keyboard returns inline keyboard with support link."""
    kb = support_inline_keyboard("usemycontent")
    assert kb is not None
    assert kb.kind == KeyboardKind.INLINE
    assert len(kb.rows) == 1
    assert len(kb.rows[0]) == 1
    assert kb.rows[0][0].text == SUPPORT_BUTTON_TEXT
    assert kb.rows[0][0].url == "https://t.me/usemycontent"


def test_support_inline_keyboard_returns_none_when_username_empty() -> None:
    """support_inline_keyboard returns None when username is empty."""
    assert support_inline_keyboard("") is None
