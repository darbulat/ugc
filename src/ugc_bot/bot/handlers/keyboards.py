"""Keyboard helpers for bot handlers."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

SUPPORT_BUTTON_TEXT = "Поддержка"
CHANGE_ROLE_BUTTON_TEXT = "Смена роли"


def support_keyboard(one_time_keyboard: bool = True) -> ReplyKeyboardMarkup:
    """Build a reply keyboard with a support button."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SUPPORT_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def with_support_keyboard(
    keyboard: list[list[KeyboardButton]],
    one_time_keyboard: bool = True,
) -> ReplyKeyboardMarkup:
    """Build a reply keyboard with a support button appended."""

    combined = list(keyboard)
    combined.append([KeyboardButton(text=SUPPORT_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=combined,
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Build a persistent main menu keyboard (Support, Change role)."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
            [KeyboardButton(text=CHANGE_ROLE_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
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
