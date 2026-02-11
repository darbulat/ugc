"""Keyboard helpers for bot handlers."""

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind

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


def support_keyboard(one_time_keyboard: bool = True) -> Keyboard:
    """Build a reply keyboard with a support button."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=SUPPORT_BUTTON_TEXT)]],
        resize=True,
        one_time=one_time_keyboard,
    )


def with_support_keyboard(
    keyboard: list[list[Button]],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Build a reply keyboard with a support button appended."""

    combined = list(keyboard)
    combined.append([Button(text=SUPPORT_BUTTON_TEXT)])
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=combined,
        resize=True,
        one_time=one_time_keyboard,
    )


def flow_keyboard(
    keyboard: list[list[Button]],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Build a reply keyboard for flow steps (no support button)."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=keyboard,
        resize=True,
        one_time=one_time_keyboard,
    )


def flow_keyboard_remove() -> Keyboard:
    """Remove keyboard during flow (no support button)."""

    return Keyboard(kind=KeyboardKind.REMOVE)


def creator_start_keyboard() -> Keyboard:
    """Keyboard for creator after role: single Create profile button."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=CREATE_PROFILE_BUTTON_TEXT)]],
        resize=True,
        one_time=True,
    )


def creator_filled_profile_keyboard(
    one_time_keyboard: bool = False,
) -> Keyboard:
    """Keyboard for creator with filled profile: Edit, Profile, Orders."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=EDIT_PROFILE_BUTTON_TEXT)],
            [Button(text=MY_PROFILE_BUTTON_TEXT)],
            [Button(text=MY_ORDERS_BUTTON_TEXT)],
            [Button(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=one_time_keyboard,
    )


def main_menu_keyboard() -> Keyboard:
    """Build persistent main menu (Support, Change role)."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=SUPPORT_BUTTON_TEXT)],
            [Button(text=CHANGE_ROLE_BUTTON_TEXT)],
        ],
        resize=True,
        is_persistent=True,
        one_time=False,
    )


def profile_keyboard(one_time_keyboard: bool = True) -> Keyboard:
    """Build a reply keyboard with a profile button."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=MY_PROFILE_BUTTON_TEXT)]],
        resize=True,
        one_time=one_time_keyboard,
    )


def advertiser_start_keyboard() -> Keyboard:
    """Keyboard after advertiser role selection: Start to fill profile only.

    'Create order' is shown only after profile is filled
    (advertiser_menu_keyboard).
    """

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=ADVERTISER_START_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=True,
    )


def advertiser_menu_keyboard(
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Build a reply keyboard for advertiser actions."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=CREATE_ORDER_BUTTON_TEXT)],
            [Button(text=MY_ORDERS_BUTTON_TEXT)],
            [Button(text=MY_PROFILE_BUTTON_TEXT)],
            [Button(text=EDIT_PROFILE_BUTTON_TEXT)],
            [Button(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=one_time_keyboard,
    )


def advertiser_after_payment_keyboard() -> Keyboard:
    """Keyboard after successful payment: Create order, My orders, Support."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=CREATE_ORDER_BUTTON_TEXT)],
            [Button(text=MY_ORDERS_BUTTON_TEXT)],
            [Button(text=SUPPORT_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=False,
    )


def blogger_menu_keyboard(
    confirmed: bool,
    one_time_keyboard: bool = False,
    verification_started: bool = False,
) -> Keyboard:
    """Build a reply keyboard for blogger actions.

    Args:
        confirmed: Whether Instagram account is verified
        one_time_keyboard: Whether to hide keyboard after use
        verification_started: If True, no verification btn (already requested)
    """
    keyboard: list[list[Button]] = []

    if not confirmed and not verification_started:
        keyboard.append([Button(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)])

    keyboard.append([Button(text=MY_PROFILE_BUTTON_TEXT)])

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=keyboard,
        resize=True,
        one_time=one_time_keyboard,
    )


def blogger_after_registration_keyboard() -> Keyboard:
    """Keyboard after profile creation: Confirm Instagram + My profile."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)],
            [Button(text=MY_PROFILE_BUTTON_TEXT)],
        ],
        resize=True,
        one_time=False,
    )


def blogger_verification_sent_keyboard() -> Keyboard:
    """Keyboard after code sent: only My profile (no verification button)."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=MY_PROFILE_BUTTON_TEXT)]],
        resize=True,
        one_time=False,
    )


def blogger_profile_view_keyboard(confirmed: bool) -> Keyboard:
    """Keyboard for My profile: Edit, Confirm Instagram if not confirmed."""

    keyboard = [[Button(text=EDIT_PROFILE_BUTTON_TEXT)]]
    if not confirmed:
        keyboard.append([Button(text=CONFIRM_INSTAGRAM_BUTTON_TEXT)])
    keyboard.append([Button(text=MY_PROFILE_BUTTON_TEXT)])
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=keyboard,
        resize=True,
        one_time=False,
    )
