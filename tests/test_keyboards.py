"""Tests for keyboard helpers."""

from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    blogger_menu_keyboard,
    cancel_keyboard,
    profile_keyboard,
    with_cancel_keyboard,
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


def test_cancel_keyboard() -> None:
    """Test cancel keyboard creation."""
    keyboard = cancel_keyboard()

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 1
    assert keyboard.keyboard[0][0].text == "Отменить"
    assert keyboard.resize_keyboard is True
    assert keyboard.one_time_keyboard is True


def test_cancel_keyboard_not_one_time() -> None:
    """Test cancel keyboard with one_time_keyboard=False."""
    keyboard = cancel_keyboard(one_time_keyboard=False)

    assert keyboard.one_time_keyboard is False


def test_with_cancel_keyboard() -> None:
    """Test keyboard with cancel button appended."""
    from aiogram.types import KeyboardButton

    original_keyboard = [
        [KeyboardButton(text="Option 1")],
        [KeyboardButton(text="Option 2")],
    ]
    keyboard = with_cancel_keyboard(original_keyboard)

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 3
    assert keyboard.keyboard[0][0].text == "Option 1"
    assert keyboard.keyboard[1][0].text == "Option 2"
    assert keyboard.keyboard[2][0].text == "Отменить"
    assert keyboard.resize_keyboard is True
    assert keyboard.one_time_keyboard is True


def test_profile_keyboard() -> None:
    """Test profile keyboard creation."""
    keyboard = profile_keyboard()

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 1
    assert keyboard.keyboard[0][0].text == "Мой профиль"
    assert keyboard.resize_keyboard is True
    assert keyboard.one_time_keyboard is True


def test_profile_keyboard_not_one_time() -> None:
    """Test profile keyboard with one_time_keyboard=False."""
    keyboard = profile_keyboard(one_time_keyboard=False)

    assert keyboard.one_time_keyboard is False


def test_advertiser_menu_keyboard() -> None:
    """Test advertiser menu keyboard."""
    keyboard = advertiser_menu_keyboard()

    assert keyboard.keyboard is not None
    assert len(keyboard.keyboard) == 4
    assert keyboard.keyboard[0][0].text == "/register_advertiser"
    assert keyboard.keyboard[1][0].text == "/create_order"
    assert keyboard.keyboard[2][0].text == "Мои заказы"
    assert keyboard.keyboard[3][0].text == "Мой профиль"
    assert keyboard.resize_keyboard is True
    assert keyboard.one_time_keyboard is True


def test_advertiser_menu_keyboard_not_one_time() -> None:
    """Test advertiser menu keyboard with one_time_keyboard=False."""
    keyboard = advertiser_menu_keyboard(one_time_keyboard=False)

    assert keyboard.one_time_keyboard is False
