"""Tests for keyboard helpers."""

from ugc_bot.application.messenger.dto import Button
from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    blogger_menu_keyboard,
    main_menu_keyboard,
    profile_keyboard,
    support_keyboard,
    with_support_keyboard,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

_TEXTS_RU = DEFAULT_TEXTS["ru"]


def test_blogger_menu_keyboard_not_confirmed() -> None:
    """Show verification button when Instagram is not confirmed."""
    keyboard = blogger_menu_keyboard(_TEXTS_RU, confirmed=False)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_confirm_instagram"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_menu_keyboard_confirmed() -> None:
    """Hide verification button when Instagram is confirmed."""
    keyboard = blogger_menu_keyboard(_TEXTS_RU, confirmed=True)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_my_profile"]


def test_blogger_menu_keyboard_one_time() -> None:
    """Respect one_time_keyboard parameter."""
    keyboard = blogger_menu_keyboard(
        _TEXTS_RU, confirmed=False, one_time_keyboard=True
    )

    assert keyboard.one_time is True


def test_blogger_menu_keyboard_resize() -> None:
    """Keyboard should always be resizable."""
    keyboard = blogger_menu_keyboard(_TEXTS_RU, confirmed=False)

    assert keyboard.resize is True


def test_support_keyboard() -> None:
    """Support keyboard has one Support button."""
    keyboard = support_keyboard(_TEXTS_RU)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_support"]


def test_with_support_keyboard_appends_support_row() -> None:
    """with_support_keyboard appends Support button row."""
    base = [[Button(text="A")]]
    keyboard = with_support_keyboard(base, _TEXTS_RU)

    assert len(keyboard.rows) == 2
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_support"]


def test_main_menu_keyboard_persistent() -> None:
    """Main menu has Support and Change role, is persistent."""
    keyboard = main_menu_keyboard(_TEXTS_RU)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_support"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_change_role"]
    assert keyboard.is_persistent is True
    assert keyboard.one_time is False


def test_advertiser_start_keyboard() -> None:
    """Advertiser start keyboard has only Start before profile filled."""
    keyboard = advertiser_start_keyboard(_TEXTS_RU)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_advertiser_start"]
    assert keyboard.rows[0][0].text == "Начать"


def test_advertiser_menu_keyboard() -> None:
    """Advertiser menu: Create order, My orders, My profile, Edit, Support."""
    keyboard = advertiser_menu_keyboard(_TEXTS_RU)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 5
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_create_order"]
    assert keyboard.rows[1][0].text == _TEXTS_RU["btn_my_orders"]
    assert keyboard.rows[2][0].text == _TEXTS_RU["btn_my_profile"]
    assert keyboard.rows[3][0].text == _TEXTS_RU["btn_edit_profile"]
    assert keyboard.rows[4][0].text == _TEXTS_RU["btn_support"]


def test_profile_keyboard() -> None:
    """Profile keyboard has single My profile button."""
    keyboard = profile_keyboard(_TEXTS_RU)

    assert keyboard.rows is not None
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].text == _TEXTS_RU["btn_my_profile"]
    assert keyboard.one_time is True


def test_profile_keyboard_one_time_false() -> None:
    """Profile keyboard respects one_time_keyboard=False."""
    keyboard = profile_keyboard(_TEXTS_RU, one_time_keyboard=False)

    assert keyboard.one_time is False
