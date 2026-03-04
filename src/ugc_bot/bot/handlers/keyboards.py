"""Keyboard helpers. All button labels come from texts (bot_texts)."""

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind

# Keys per keyboard in docstrings. Use bot_texts_service.get_many(keys, locale).

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
CALLBACK_BLOGGER_REGION_PREFIX = "blogger:region:"
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
CALLBACK_PROFILE_REGION_PREFIX = "profile:region:"


def support_keyboard(
    texts: dict[str, str],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Build a reply keyboard with a support button. Needs: btn_support."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=texts["btn_support"])]],
        resize=True,
        one_time=one_time_keyboard,
    )


def with_support_keyboard(
    keyboard: list[list[Button]],
    texts: dict[str, str],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Reply keyboard with support button appended. Needs: btn_support."""

    combined = list(keyboard)
    combined.append([Button(text=texts["btn_support"])])
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


def phone_request_keyboard(texts: dict[str, str]) -> Keyboard:
    """Reply keyboard: share phone. Needs: btn_phone_request."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=texts["btn_phone_request"], request_contact=True)]],
        resize=True,
        one_time=True,
    )


def flow_inline_keyboard(rows: list[list[Button]]) -> Keyboard:
    """Inline keyboard for flow steps; buttons must have callback_data."""

    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def role_keyboard(texts: dict[str, str]) -> Keyboard:
    """Role selection. Needs: btn_creator, btn_advertiser, btn_support."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_creator"])],
            [Button(text=texts["btn_advertiser"])],
            [Button(text=texts["btn_support"])],
        ],
        resize=True,
        one_time=True,
    )


def creator_start_keyboard(texts: dict[str, str]) -> Keyboard:
    """Creator after role: Create profile. Needs: btn_create_profile."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_create_profile"],
                    callback_data=CALLBACK_CREATOR_CREATE,
                )
            ]
        ],
    )


def creator_start_keyboard_reply(texts: dict[str, str]) -> Keyboard:
    """Legacy reply keyboard for creator start. Needs: btn_create_profile."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=texts["btn_create_profile"])]],
        resize=True,
        one_time=True,
    )


def creator_filled_profile_keyboard(
    texts: dict[str, str],
    one_time_keyboard: bool = False,
) -> Keyboard:
    """Creator filled profile: Edit, Profile, Orders. Needs: btn_*."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_edit_profile"])],
            [Button(text=texts["btn_my_profile"])],
            [Button(text=texts["btn_my_orders"])],
            [Button(text=texts["btn_support"])],
        ],
        resize=True,
        one_time=one_time_keyboard,
    )


def main_menu_keyboard(texts: dict[str, str]) -> Keyboard:
    """Main menu: Support, Change role. Needs: btn_support, btn_change_role."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_support"])],
            [Button(text=texts["btn_change_role"])],
        ],
        resize=True,
        is_persistent=True,
        one_time=False,
    )


def profile_keyboard(
    texts: dict[str, str],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Reply keyboard with profile button. Needs: btn_my_profile."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=texts["btn_my_profile"])]],
        resize=True,
        one_time=one_time_keyboard,
    )


def advertiser_start_keyboard(texts: dict[str, str]) -> Keyboard:
    """Advertiser role: Start (inline). Needs: btn_advertiser_start."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_advertiser_start"],
                    callback_data=CALLBACK_ADV_START,
                )
            ]
        ],
    )


def confirm_agreement_inline_keyboard(
    callback_data: str,
    texts: dict[str, str],
) -> Keyboard:
    """Inline: Confirm agreement. Needs: btn_confirm_agreement."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_confirm_agreement"],
                    callback_data=callback_data,
                )
            ]
        ],
    )


def advertiser_menu_keyboard(
    texts: dict[str, str],
    one_time_keyboard: bool = True,
) -> Keyboard:
    """Advertiser menu. Needs: btn_create_order, btn_my_orders, btn_*."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_create_order"])],
            [Button(text=texts["btn_my_orders"])],
            [Button(text=texts["btn_my_profile"])],
            [Button(text=texts["btn_edit_profile"])],
            [Button(text=texts["btn_support"])],
        ],
        resize=True,
        one_time=one_time_keyboard,
    )


def advertiser_after_payment_keyboard(texts: dict[str, str]) -> Keyboard:
    """After payment: Create order, My orders, Support. Needs: btn_*."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_create_order"])],
            [Button(text=texts["btn_my_orders"])],
            [Button(text=texts["btn_support"])],
        ],
        resize=True,
        one_time=False,
    )


def blogger_menu_keyboard(
    texts: dict[str, str],
    confirmed: bool,
    one_time_keyboard: bool = False,
    verification_started: bool = False,
) -> Keyboard:
    """Blogger menu. Needs: btn_confirm_instagram, btn_my_profile."""

    keyboard: list[list[Button]] = []
    if not confirmed and not verification_started:
        keyboard.append([Button(text=texts["btn_confirm_instagram"])])
    keyboard.append([Button(text=texts["btn_my_profile"])])
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=keyboard,
        resize=True,
        one_time=one_time_keyboard,
    )


def blogger_after_registration_keyboard(texts: dict[str, str]) -> Keyboard:
    """After blogger reg. Needs: btn_confirm_instagram, btn_my_profile."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[
            [Button(text=texts["btn_confirm_instagram"])],
            [Button(text=texts["btn_my_profile"])],
        ],
        resize=True,
        one_time=False,
    )


def blogger_verification_sent_keyboard(texts: dict[str, str]) -> Keyboard:
    """After code sent: My profile only. Needs: btn_my_profile."""

    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=texts["btn_my_profile"])]],
        resize=True,
        one_time=False,
    )


def blogger_profile_view_keyboard(
    texts: dict[str, str],
    confirmed: bool,
) -> Keyboard:
    """Profile keys: btn_edit_profile, btn_confirm_instagram, btn_my_profile."""

    keyboard = [[Button(text=texts["btn_edit_profile"])]]
    if not confirmed:
        keyboard.append([Button(text=texts["btn_confirm_instagram"])])
    keyboard.append([Button(text=texts["btn_my_profile"])])
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=keyboard,
        resize=True,
        one_time=False,
    )


def advertiser_menu_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Inline: Create order, My orders, Profile, Edit. Needs: btn_*."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_create_order"],
                    callback_data=CALLBACK_PROFILE_MENU_CREATE_ORDER,
                )
            ],
            [
                Button(
                    text=texts["btn_my_orders"],
                    callback_data=CALLBACK_PROFILE_MENU_MY_ORDERS,
                )
            ],
            [
                Button(
                    text=texts["btn_my_profile"],
                    callback_data=CALLBACK_PROFILE_MY_PROFILE,
                ),
                Button(
                    text=texts["btn_edit_profile"],
                    callback_data=CALLBACK_PROFILE_EDIT,
                ),
            ],
        ],
    )


def blogger_profile_view_inline_keyboard(
    texts: dict[str, str],
    confirmed: bool,
) -> Keyboard:
    """Inline: Edit, Confirm Instagram, Back. Needs: btn_*."""

    rows: list[list[Button]] = [
        [
            Button(
                text=texts["btn_edit_profile"],
                callback_data=CALLBACK_PROFILE_EDIT,
            )
        ],
    ]
    if not confirmed:
        rows.append(
            [
                Button(
                    text=texts["btn_confirm_instagram"],
                    callback_data=CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
                )
            ]
        )
    rows.append(
        [
            Button(
                text=texts["btn_my_profile"],
                callback_data=CALLBACK_PROFILE_MY_PROFILE,
            )
        ]
    )
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def edit_profile_type_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Edit type keys: btn_edit_profile_blogger, btn_edit_profile_advertiser."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_edit_profile_blogger"],
                    callback_data=CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
                )
            ],
            [
                Button(
                    text=texts["btn_edit_profile_advertiser"],
                    callback_data=CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
                )
            ],
            [
                Button(
                    text=texts["btn_my_profile"],
                    callback_data=CALLBACK_PROFILE_MY_PROFILE,
                )
            ],
        ],
    )


def edit_field_inline_keyboard(
    field_rows: list[list[tuple[str, str]]],
    texts: dict[str, str],
) -> Keyboard:
    """Profile fields (label, key). Needs: btn_my_profile."""

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
                text=texts["btn_my_profile"],
                callback_data=CALLBACK_PROFILE_MY_PROFILE,
            ),
        ]
    )
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


def edit_audience_gender_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Audience. Needs: btn_audience_f, btn_audience_m, btn_audience_a."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_audience_f"],
                    callback_data=CALLBACK_PROFILE_AUDIENCE_F,
                ),
                Button(
                    text=texts["btn_audience_m"],
                    callback_data=CALLBACK_PROFILE_AUDIENCE_M,
                ),
            ],
            [
                Button(
                    text=texts["btn_audience_a"],
                    callback_data=CALLBACK_PROFILE_AUDIENCE_A,
                )
            ],
        ],
    )


def edit_blogger_gender_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Blogger gender choice. Needs: btn_gender_m, btn_gender_f."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_gender_m"],
                    callback_data=CALLBACK_PROFILE_BLOGGER_GENDER_M,
                ),
                Button(
                    text=texts["btn_gender_f"],
                    callback_data=CALLBACK_PROFILE_BLOGGER_GENDER_F,
                ),
            ],
        ],
    )


def edit_audience_age_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Audience age choice. Needs: btn_age_*."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_age_0_17"],
                    callback_data=CALLBACK_PROFILE_AGE_0_17,
                ),
                Button(
                    text=texts["btn_age_18_24"],
                    callback_data=CALLBACK_PROFILE_AGE_18_24,
                ),
                Button(
                    text=texts["btn_age_25_34"],
                    callback_data=CALLBACK_PROFILE_AGE_25_34,
                ),
            ],
            [
                Button(
                    text=texts["btn_age_35_44"],
                    callback_data=CALLBACK_PROFILE_AGE_35_44,
                ),
                Button(
                    text=texts["btn_age_45_99"],
                    callback_data=CALLBACK_PROFILE_AGE_45_99,
                ),
            ],
        ],
    )


def edit_barter_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Barter choice. Needs: btn_barter_yes, btn_barter_no."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_barter_yes"],
                    callback_data=CALLBACK_PROFILE_BARTER_Y,
                ),
                Button(
                    text=texts["btn_barter_no"],
                    callback_data=CALLBACK_PROFILE_BARTER_N,
                ),
            ],
        ],
    )


def edit_work_format_inline_keyboard(texts: dict[str, str]) -> Keyboard:
    """Work format. Needs: btn_work_format_ads, btn_work_format_ugc_only."""

    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts["btn_work_format_ads"],
                    callback_data=CALLBACK_PROFILE_WORK_ADS,
                )
            ],
            [
                Button(
                    text=texts["btn_work_format_ugc_only"],
                    callback_data=CALLBACK_PROFILE_WORK_UGC,
                )
            ],
        ],
    )
