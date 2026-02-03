"""Keyboard helpers for bot handlers."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

SUPPORT_BUTTON_TEXT = "💬 Поддержка"
MY_ORDERS_BUTTON_TEXT = "📂 Мои заказы"
CHANGE_ROLE_BUTTON_TEXT = "Смена роли"
CREATE_PROFILE_BUTTON_TEXT = "Создать профиль"
ADVERTISER_START_BUTTON_TEXT = "Начать"
CREATE_ORDER_BUTTON_TEXT = "➕ Создать заказ"
CONFIRM_INSTAGRAM_BUTTON_TEXT = "✅ Подтвердить Instagram"
CONFIRM_AGREEMENT_BUTTON_TEXT = "✅ Подтвердить согласие"
EDIT_PROFILE_BUTTON_TEXT = "Редактировать профиль"
MY_PROFILE_BUTTON_TEXT = "👤 Мой профиль"
WORK_FORMAT_ADS_BUTTON_TEXT = "📢 Размещать рекламу у себя в аккаунте"
WORK_FORMAT_UGC_ONLY_BUTTON_TEXT = "❌ Только UGC (без размещения)"
RESUME_DRAFT_BUTTON_TEXT = "Продолжить"
START_OVER_BUTTON_TEXT = "Начать заново"

DRAFT_QUESTION_TEXT = "У вас есть черновик. Продолжить?"
DRAFT_RESTORED_TEXT = "Черновик восстановлен."


def draft_choice_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard for draft restore: Continue or Start over."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=RESUME_DRAFT_BUTTON_TEXT)],
            [KeyboardButton(text=START_OVER_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


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


def creator_start_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard for creator right after role selection: single Create profile button."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CREATE_PROFILE_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def creator_filled_profile_keyboard(
    one_time_keyboard: bool = False,
) -> ReplyKeyboardMarkup:
    """Keyboard for creator with filled profile: Edit profile, My profile, My orders."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=EDIT_PROFILE_BUTTON_TEXT)],
            [KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)],
            [KeyboardButton(text=MY_ORDERS_BUTTON_TEXT)],
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
        ],
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
        keyboard=[[KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def advertiser_start_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard after advertiser role selection: single Start button."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=ADVERTISER_START_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def advertiser_menu_keyboard(one_time_keyboard: bool = True) -> ReplyKeyboardMarkup:
    """Build a reply keyboard for advertiser actions."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CREATE_ORDER_BUTTON_TEXT)],
            [KeyboardButton(text=MY_ORDERS_BUTTON_TEXT)],
            [KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)],
            [KeyboardButton(text=EDIT_PROFILE_BUTTON_TEXT)],
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def advertiser_after_payment_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard after successful payment: My orders and Support only."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MY_ORDERS_BUTTON_TEXT)],
            [KeyboardButton(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def blogger_menu_keyboard(
    confirmed: bool,
    one_time_keyboard: bool = False,
    verification_started: bool = False,
) -> ReplyKeyboardMarkup:
    """Build a reply keyboard for blogger actions.

    Args:
        confirmed: Whether Instagram account is verified
        one_time_keyboard: Whether to hide keyboard after use
        verification_started: If True, do not show verification button (user already requested code)
    """
    keyboard = []

    if not confirmed and not verification_started:
        keyboard.append([KeyboardButton(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)])

    keyboard.append([KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=one_time_keyboard,
    )


def blogger_after_registration_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown right after profile creation: Confirm Instagram + My profile."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)],
            [KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def blogger_verification_sent_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard after verification code sent: only My profile (no verification button)."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def blogger_profile_view_keyboard(confirmed: bool) -> ReplyKeyboardMarkup:
    """Keyboard when viewing My profile: Edit profile + My profile, and Confirm Instagram if not confirmed."""

    keyboard = [[KeyboardButton(text=EDIT_PROFILE_BUTTON_TEXT)]]
    if not confirmed:
        keyboard.append([KeyboardButton(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)])
    keyboard.append([KeyboardButton(text=MY_PROFILE_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
    )
