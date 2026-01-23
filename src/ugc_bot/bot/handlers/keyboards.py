"""Keyboard helpers for bot handlers."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def cancel_keyboard(one_time_keyboard: bool = True) -> ReplyKeyboardMarkup:
    """Build a reply keyboard with a cancel button."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отменить")]],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def with_cancel_keyboard(
    keyboard: list[list[KeyboardButton]],
    one_time_keyboard: bool = True,
) -> ReplyKeyboardMarkup:
    """Build a reply keyboard with a cancel button appended."""

    combined = list(keyboard)
    combined.append([KeyboardButton(text="Отменить")])
    return ReplyKeyboardMarkup(
        keyboard=combined,
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def profile_keyboard(one_time_keyboard: bool = True) -> ReplyKeyboardMarkup:
    """Build a reply keyboard with a profile button."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Мой профиль")]],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def advertiser_menu_keyboard(one_time_keyboard: bool = True) -> ReplyKeyboardMarkup:
    """Build a reply keyboard for advertiser actions."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/register_advertiser")],
            [KeyboardButton(text="/create_order")],
            [KeyboardButton(text="Мои заказы")],
            [KeyboardButton(text="Мой профиль")],
        ],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def blogger_menu_keyboard(
    confirmed: bool, one_time_keyboard: bool = False
) -> ReplyKeyboardMarkup:
    """Build a reply keyboard for blogger actions.

    Args:
        confirmed: Whether Instagram account is verified
        one_time_keyboard: Whether to hide keyboard after use
    """
    keyboard = []

    # Show verification button if not confirmed
    if not confirmed:
        keyboard.append([KeyboardButton(text="Пройти верификацию")])

    keyboard.append([KeyboardButton(text="Мой профиль")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )
