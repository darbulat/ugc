"""Tests for keyboard helpers."""

from ugc_bot.bot.handlers.keyboards import (
    blogger_menu_keyboard,
    main_menu_keyboard,
    support_keyboard,
    with_support_keyboard,
)


def test_blogger_menu_keyboard_not_confirmed() -> None:
    """Show verification button when Instagram is not confirmed."""
    keyboard = blogger_menu_keyboard(confirmed=False)

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[0][0].text == "Пройти верификацию"
    assert keyboard.keyboard[1][0].text == "Мой профиль"


def test_blogger_menu_keyboard_confirmed() -> None:
    """Hide verification button when Instagram is confirmed."""
    keyboard = blogger_menu_keyboard(confirmed=True)

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 1
    assert keyboard.keyboard[0][0].text == "Мой профиль"


def test_blogger_menu_keyboard_one_time() -> None:
    """Respect one_time_keyboard parameter."""
    keyboard = blogger_menu_keyboard(confirmed=False, one_time_keyboard=True)

    assert keyboard.one_time_keyboard is True


def test_blogger_menu_keyboard_resize() -> None:
    """Keyboard should always be resizable."""
    keyboard = blogger_menu_keyboard(confirmed=False)

    assert keyboard.resize_keyboard is True


def test_support_keyboard() -> None:
    """Support keyboard has one Support button."""
    keyboard = support_keyboard()

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 1
    assert keyboard.keyboard[0][0].text == "Поддержка"


def test_with_support_keyboard_appends_support_row() -> None:
    """with_support_keyboard appends Support button row."""
    from aiogram.types import KeyboardButton

    base = [[KeyboardButton(text="A")]]
    keyboard = with_support_keyboard(base)

    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[1][0].text == "Поддержка"


def test_main_menu_keyboard_persistent() -> None:
    """Main menu has Support and Change role, is persistent."""
    keyboard = main_menu_keyboard()

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[0][0].text == "Поддержка"
    assert keyboard.keyboard[1][0].text == "Смена роли"
    assert keyboard.is_persistent is True
    assert keyboard.one_time_keyboard is False
