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
PHONE_REQUEST_BUTTON_TEXT = "📱 Поделиться номером телефона"

# Inline callback_data (Telegram limit 64 bytes)
CALLBACK_CREATOR_CREATE = "creator:create"
CALLBACK_ADV_START = "adv:start"
CALLBACK_ADV_AGREE = "adv:agree"
CALLBACK_BLOGGER_AGREE = "blogger:agree"
CALLBACK_BLOGGER_GENDER_M = "blogger:gender:M"
CALLBACK_BLOGGER_GENDER_F = "blogger:gender:F"
CALLBACK_BLOGGER_AUDIENCE_F = "blogger:aud:F"
CALLBACK_BLOGGER_AUDIENCE_M = "blogger:aud:M"
CALLBACK_BLOGGER_AUDIENCE_A = "blogger:aud:A"
CALLBACK_BLOGGER_AGE_PREFIX = "blogger:age:"
CALLBACK_BLOGGER_AGE_0_17 = "blogger:age:0_17"
CALLBACK_BLOGGER_AGE_18_24 = "blogger:age:18_24"
CALLBACK_BLOGGER_AGE_25_34 = "blogger:age:25_34"
CALLBACK_BLOGGER_AGE_35_44 = "blogger:age:35_44"
CALLBACK_BLOGGER_AGE_45_99 = "blogger:age:45_99"
CALLBACK_BLOGGER_BARTER_Y = "blogger:barter:Y"
CALLBACK_BLOGGER_BARTER_N = "blogger:barter:N"
CALLBACK_BLOGGER_WORK_ADS = "blogger:work:ads"
CALLBACK_BLOGGER_WORK_UGC = "blogger:work:ugc"
CALLBACK_ORDER_AGREE = "order:agree"
CALLBACK_PROFILE_AGREE = "profile:agree"
CALLBACK_PROFILE_EDIT = "profile:menu:edit"
CALLBACK_PROFILE_MY_PROFILE = "profile:menu:profile"
CALLBACK_PROFILE_EDIT_TYPE_BLOGGER = "profile:type:blogger"
CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER = "profile:type:advertiser"
CALLBACK_PROFILE_EDIT_FIELD_PREFIX = "profile:field:"
CALLBACK_PROFILE_MENU_CREATE_ORDER = "profile:menu:order"
CALLBACK_PROFILE_MENU_MY_ORDERS = "profile:menu:orders"
CALLBACK_PROFILE_CONFIRM_INSTAGRAM = "profile:confirm_ig"
PAY_ORDER_CALLBACK_PREFIX = "pay_order:"
# Edit choice fields (blogger)
CALLBACK_PROFILE_AUDIENCE_F = "profile:aud:F"
CALLBACK_PROFILE_AUDIENCE_M = "profile:aud:M"
CALLBACK_PROFILE_AUDIENCE_A = "profile:aud:A"
CALLBACK_PROFILE_BLOGGER_GENDER_M = "profile:bg:M"
CALLBACK_PROFILE_BLOGGER_GENDER_F = "profile:bg:F"
CALLBACK_PROFILE_AGE_0_17 = "profile:age:0_17"
CALLBACK_PROFILE_AGE_18_24 = "profile:age:18_24"
CALLBACK_PROFILE_AGE_25_34 = "profile:age:25_34"
CALLBACK_PROFILE_AGE_35_44 = "profile:age:35_44"
CALLBACK_PROFILE_AGE_45_99 = "profile:age:45_99"
CALLBACK_PROFILE_BARTER_Y = "profile:barter:Y"
CALLBACK_PROFILE_BARTER_N = "profile:barter:N"
CALLBACK_PROFILE_WORK_ADS = "profile:work:ads"
CALLBACK_PROFILE_WORK_UGC = "profile:work:ugc"


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


def phone_request_keyboard() -> Keyboard:
    """Reply keyboard: one button to share phone (request_contact)."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=PHONE_REQUEST_BUTTON_TEXT, request_contact=True)]],
        resize=True,
        one_time=True,
    )


def flow_inline_keyboard(rows: list[list[Button]]) -> Keyboard:
    """Inline keyboard for flow steps; buttons must have callback_data."""

    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def creator_start_keyboard() -> Keyboard:
    """Creator after role: single Create profile button (inline)."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=CREATE_PROFILE_BUTTON_TEXT,
                    callback_data=CALLBACK_CREATOR_CREATE,
                )
            ]
        ],
    )


def creator_start_keyboard_reply() -> Keyboard:
    """Legacy reply keyboard for creator start (for tests if needed)."""

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
    """Keyboard after advertiser role selection: Start (inline)."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=ADVERTISER_START_BUTTON_TEXT,
                    callback_data=CALLBACK_ADV_START,
                )
            ]
        ],
    )


def confirm_agreement_inline_keyboard(callback_data: str) -> Keyboard:
    """Inline keyboard with single Confirm agreement button."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=CONFIRM_AGREEMENT_BUTTON_TEXT,
                    callback_data=callback_data,
                )
            ]
        ],
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
    """Build a reply keyboard for My profile (legacy)."""

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


def advertiser_menu_inline_keyboard() -> Keyboard:
    """Inline: Create order, My orders, Profile, Edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=CREATE_ORDER_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
                )
            ],
            [
                Button(
                    text=MY_ORDERS_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_MENU_MY_ORDERS,
                )
            ],
            [
                Button(
                    text=MY_PROFILE_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_MY_PROFILE,
                ),
                Button(
                    text=EDIT_PROFILE_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_EDIT,
                ),
            ],
        ],
    )


def blogger_profile_view_inline_keyboard(confirmed: bool) -> Keyboard:
    """Inline: Edit, Confirm Instagram, Back (blogger profile)."""

    rows: list[list[Button]] = [
        [
            Button(
                text=EDIT_PROFILE_BUTTON_TEXT,
                callback_data=CALLBACK_PROFILE_EDIT,
            )
        ],
    ]
    if not confirmed:
        rows.append(
            [
                Button(
                    text=CONFIRM_INSTAGRAM_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
                )
            ]
        )
    rows.append(
        [
            Button(
                text=MY_PROFILE_BUTTON_TEXT,
                callback_data=CALLBACK_PROFILE_MY_PROFILE,
            )
        ]
    )
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def edit_profile_type_inline_keyboard() -> Keyboard:
    """Inline keyboard to choose blogger or advertiser profile to edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="Редактировать профиль блогера",
                    callback_data=CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
                )
            ],
            [
                Button(
                    text="Редактировать профиль рекламодателя",
                    callback_data=CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
                )
            ],
            [
                Button(
                    text=MY_PROFILE_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_MY_PROFILE,
                )
            ],
        ],
    )


def edit_field_inline_keyboard(
    field_rows: list[list[tuple[str, str]]],
) -> Keyboard:
    """Profile fields (label, key); callback profile:field:key."""

    rows: list[list[Button]] = []
    for row in field_rows:
        rows.append(
            [
                Button(
                    text=label,
                    callback_data=CALLBACK_PROFILE_EDIT_FIELD_PREFIX + key,
                )
                for label, key in row
            ]
        )
    rows.append(
        [
            Button(
                text=MY_PROFILE_BUTTON_TEXT,
                callback_data=CALLBACK_PROFILE_MY_PROFILE,
            ),
        ]
    )
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def edit_audience_gender_inline_keyboard() -> Keyboard:
    """Inline keyboard for audience gender choice in profile edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="👩 В основном женщины",
                    callback_data=CALLBACK_PROFILE_AUDIENCE_F,
                ),
                Button(
                    text="👨 В основном мужчины",
                    callback_data=CALLBACK_PROFILE_AUDIENCE_M,
                ),
            ],
            [
                Button(
                    text="👥 Примерно поровну",
                    callback_data=CALLBACK_PROFILE_AUDIENCE_A,
                )
            ],
        ],
    )


def edit_blogger_gender_inline_keyboard() -> Keyboard:
    """Inline keyboard for blogger gender choice in profile edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="Мужской",
                    callback_data=CALLBACK_PROFILE_BLOGGER_GENDER_M,
                ),
                Button(
                    text="Женский",
                    callback_data=CALLBACK_PROFILE_BLOGGER_GENDER_F,
                ),
            ],
        ],
    )


def edit_audience_age_inline_keyboard() -> Keyboard:
    """Inline keyboard for audience age choice in profile edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(text="до 18", callback_data=CALLBACK_PROFILE_AGE_0_17),
                Button(text="18–24", callback_data=CALLBACK_PROFILE_AGE_18_24),
                Button(text="25–34", callback_data=CALLBACK_PROFILE_AGE_25_34),
            ],
            [
                Button(text="35–44", callback_data=CALLBACK_PROFILE_AGE_35_44),
                Button(text="45+", callback_data=CALLBACK_PROFILE_AGE_45_99),
            ],
        ],
    )


def edit_barter_inline_keyboard() -> Keyboard:
    """Inline keyboard for barter choice in profile edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(text="Да", callback_data=CALLBACK_PROFILE_BARTER_Y),
                Button(text="Нет", callback_data=CALLBACK_PROFILE_BARTER_N),
            ],
        ],
    )


def edit_work_format_inline_keyboard() -> Keyboard:
    """Inline keyboard for work format choice in profile edit."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=WORK_FORMAT_ADS_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_WORK_ADS,
                )
            ],
            [
                Button(
                    text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
                    callback_data=CALLBACK_PROFILE_WORK_UGC,
                )
            ],
        ],
    )
