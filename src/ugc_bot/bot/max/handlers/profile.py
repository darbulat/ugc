"""Max messenger profile view and edit handlers.

Differences from Telegram:
- No miniapp buttons (no location picker).
- After field update, calls Max-native _send_profile instead of
  Telegram show_profile.
"""

import logging
from typing import Any, cast

from ugc_bot.application.messenger.context import MessageContext
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_AGE_0_17,
    CALLBACK_PROFILE_AGE_18_24,
    CALLBACK_PROFILE_AGE_25_34,
    CALLBACK_PROFILE_AGE_35_44,
    CALLBACK_PROFILE_AGE_45_99,
    CALLBACK_PROFILE_AGREE,
    CALLBACK_PROFILE_AUDIENCE_A,
    CALLBACK_PROFILE_AUDIENCE_F,
    CALLBACK_PROFILE_AUDIENCE_M,
    CALLBACK_PROFILE_BARTER_N,
    CALLBACK_PROFILE_BARTER_Y,
    CALLBACK_PROFILE_BLOGGER_GENDER_F,
    CALLBACK_PROFILE_BLOGGER_GENDER_M,
    CALLBACK_PROFILE_EDIT,
    CALLBACK_PROFILE_EDIT_FIELD_PREFIX,
    CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
    CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
    CALLBACK_PROFILE_MY_PROFILE,
    CALLBACK_PROFILE_WORK_ADS,
    CALLBACK_PROFILE_WORK_UGC,
    advertiser_menu_inline_keyboard,
    blogger_profile_view_inline_keyboard,
    confirm_agreement_inline_keyboard,
    edit_audience_age_inline_keyboard,
    edit_audience_gender_inline_keyboard,
    edit_barter_inline_keyboard,
    edit_blogger_gender_inline_keyboard,
    edit_field_inline_keyboard,
    edit_profile_type_inline_keyboard,
    edit_work_format_inline_keyboard,
    flow_inline_keyboard_location_request,
    flow_inline_keyboard_phone_request,
    flow_keyboard_remove,
)
from ugc_bot.bot.telegram.handlers.profile import (
    _ADVERTISER_AGREEMENTS_STATE,
    _BLOGGER_AGREEMENTS_STATE,
    _EDIT_FIELDS_ADVERTISER_BY_KEY,
    _EDIT_FIELDS_BY_KEY,
    EDIT_FIELD_KEYS,
    EDIT_FIELD_KEYS_ADVERTISER,
    EDIT_FIELD_LABEL_KEYS_ADVERTISER,
    EDIT_FIELD_LABEL_KEYS_BLOGGER,
    PROFILE_DISPLAY_KEYS,
    PROFILE_EDIT_MSG_KEYS,
    PROMPT_EDIT_GENERIC,
    PROMPT_EDIT_KEYS_ADVERTISER,
    PROMPT_EDIT_KEYS_BLOGGER,
    EditProfileStates,
    _adv_update_brand,
    _adv_update_city,
    _adv_update_company_activity,
    _adv_update_contact,
    _adv_update_site_link,
    _blog_update_audience_age,
    _blog_update_audience_gender,
    _blog_update_audience_geo,
    _blog_update_barter,
    _blog_update_birth_date,
    _blog_update_blogger_gender,
    _blog_update_city,
    _blog_update_instagram,
    _blog_update_price,
    _blog_update_topics,
    _blog_update_work_format,
    _format_profile_text,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    parse_user_id_from_state,
    resolve_currency_symbol,
)
from ugc_bot.bot.telegram.validators import (
    VALIDATOR_ERR_KEYS,
    validate_name,
    validate_nickname,
)

router = MaxRouter()
logger = logging.getLogger(__name__)

# FSM state name constants for edit flow.
# These are always defined as non-None strings at runtime; cast to str for mypy.
_STATE_CHOOSING_PROFILE_TYPE = cast(
    str, EditProfileStates.choosing_profile_type.state
)
_STATE_CHOOSING_FIELD = cast(str, EditProfileStates.choosing_field.state)
_STATE_ENTERING_VALUE = cast(str, EditProfileStates.entering_value.state)

_PROFILE_CHOICE_CALLBACKS = frozenset(
    {
        CALLBACK_PROFILE_AUDIENCE_F,
        CALLBACK_PROFILE_AUDIENCE_M,
        CALLBACK_PROFILE_AUDIENCE_A,
        CALLBACK_PROFILE_BLOGGER_GENDER_M,
        CALLBACK_PROFILE_BLOGGER_GENDER_F,
        CALLBACK_PROFILE_AGE_0_17,
        CALLBACK_PROFILE_AGE_18_24,
        CALLBACK_PROFILE_AGE_25_34,
        CALLBACK_PROFILE_AGE_35_44,
        CALLBACK_PROFILE_AGE_45_99,
        CALLBACK_PROFILE_BARTER_Y,
        CALLBACK_PROFILE_BARTER_N,
        CALLBACK_PROFILE_WORK_ADS,
        CALLBACK_PROFILE_WORK_UGC,
    }
)

_CALLBACK_TO_CHOICE_KEY: dict[str, str] = {
    CALLBACK_PROFILE_AUDIENCE_F: "btn_audience_f",
    CALLBACK_PROFILE_AUDIENCE_M: "btn_audience_m",
    CALLBACK_PROFILE_AUDIENCE_A: "btn_audience_a",
    CALLBACK_PROFILE_BLOGGER_GENDER_M: "btn_gender_m",
    CALLBACK_PROFILE_BLOGGER_GENDER_F: "btn_gender_f",
    CALLBACK_PROFILE_AGE_0_17: "btn_age_0_17",
    CALLBACK_PROFILE_AGE_18_24: "btn_age_18_24",
    CALLBACK_PROFILE_AGE_25_34: "btn_age_25_34",
    CALLBACK_PROFILE_AGE_35_44: "btn_age_35_44",
    CALLBACK_PROFILE_AGE_45_99: "btn_age_45_99",
    CALLBACK_PROFILE_BARTER_Y: "btn_barter_yes",
    CALLBACK_PROFILE_BARTER_N: "btn_barter_no",
}


def _edit_field_rows(
    profile_type: str = "blogger",
    texts: dict[str, str] | None = None,
) -> list[list[tuple[str, str]]]:
    """Rows (label, key) for edit field inline keyboard, two per row."""
    t = texts or {}
    fields = (
        _EDIT_FIELDS_ADVERTISER_BY_KEY
        if profile_type == "advertiser"
        else _EDIT_FIELDS_BY_KEY
    )
    rows: list[list[tuple[str, str]]] = []
    for i in range(0, len(fields), 2):
        label_key1, fkey1 = fields[i]
        row: list[tuple[str, str]] = [(t.get(label_key1, label_key1), fkey1)]
        if i + 1 < len(fields):
            label_key2, fkey2 = fields[i + 1]
            row.append((t.get(label_key2, label_key2), fkey2))
        rows.append(row)
    return rows


def _get_edit_field_keyboard(
    field_key: str,
    profile_type: str,
    edit_texts: dict[str, str],
):
    """Return inline keyboard for editing the given field (no miniapp/phone)."""
    if field_key == "audience_gender":
        return edit_audience_gender_inline_keyboard(edit_texts)
    if field_key == "blogger_gender":
        return edit_blogger_gender_inline_keyboard(edit_texts)
    if field_key == "audience_age":
        return edit_audience_age_inline_keyboard(edit_texts)
    if field_key == "barter":
        return edit_barter_inline_keyboard(edit_texts)
    if field_key == "work_format":
        return edit_work_format_inline_keyboard(edit_texts)
    if field_key == "phone":
        return flow_inline_keyboard_phone_request(edit_texts)
    if field_key == "city":
        return flow_inline_keyboard_location_request(edit_texts)
    # instagram — plain text input on Max
    return flow_keyboard_remove()


async def _send_profile(
    incoming: IncomingMessage | IncomingCallback,
    deps: dict,
) -> None:
    """Fetch and send profile text + keyboard for the current user."""
    messenger_client = deps["messenger_client"]
    profile_service = deps["profile_service"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    state_store = deps["state_store"]
    country_repo = deps.get("country_repo")
    locale = deps.get("locale", "ru")

    if incoming.user is None or not incoming.user.external_id:
        return

    user = await profile_service.get_user_by_external(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None:
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found_role", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_found,
        )
        return

    currency_symbol = await resolve_currency_symbol(
        user, country_repo, config.market.currency_symbol
    )
    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)

    needs_agreement = (
        blogger is not None and blogger.agreement_confirmed_at is None
    ) or (advertiser is not None and advertiser.agreement_confirmed_at is None)
    if needs_agreement:
        agree_keys = [
            "btn_confirm_agreement",
            "msg_confirm_agreement",
            "msg_agreements_intro_default",
            "msg_label_offer",
            "msg_label_privacy",
            "msg_label_consent",
            "msg_confirm_docs_fallback",
        ]
        agree_texts = await bot_texts_service.get_many(agree_keys, locale)
        agreements_text = format_agreements_message(
            config,
            intro=agree_texts.get("msg_confirm_agreement"),
            texts=agree_texts,
            country_code=user.country,
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=confirm_agreement_inline_keyboard(
                CALLBACK_PROFILE_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state_store.update_data(user_id=str(user.user_id))
        if blogger is not None:
            await state_store.set_state(_BLOGGER_AGREEMENTS_STATE)
        else:
            await state_store.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    profile_texts = await bot_texts_service.get_many(
        list(PROFILE_DISPLAY_KEYS), locale
    )
    text = _format_profile_text(
        user,
        blogger,
        advertiser,
        currency_symbol,
        texts=profile_texts,
    )

    reply_markup = None
    if blogger is not None:
        blog_texts = await bot_texts_service.get_many(
            ["btn_edit_profile", "btn_confirm_instagram", "btn_my_profile"],
            locale,
        )
        reply_markup = blogger_profile_view_inline_keyboard(
            blog_texts, blogger.confirmed
        )
    elif advertiser is not None:
        adv_texts = await bot_texts_service.get_many(
            [
                "btn_create_order",
                "btn_my_orders",
                "btn_my_profile",
                "btn_edit_profile",
            ],
            locale,
        )
        reply_markup = advertiser_menu_inline_keyboard(adv_texts)

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=reply_markup,
    )


async def _handle_advertiser_field_update(
    incoming: IncomingMessage,
    field_key: str,
    text: str,
    deps: dict,
) -> bool:
    """Validate and update advertiser field. Returns True on success."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    advertiser_registration_service = deps["advertiser_registration_service"]
    user_role_service = deps["user_role_service"]
    profile_service = deps["profile_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    if user_id is None or not external_id_raw:
        await state_store.clear()
        return False

    advertiser = await profile_service.get_advertiser_profile(user_id)
    if advertiser is None:
        await state_store.clear()
        return False

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    edit_msgs = await bot_texts_service.get_many(
        list(PROFILE_EDIT_MSG_KEYS), locale
    )
    adv_keys = [
        "btn_create_order",
        "btn_my_orders",
        "btn_my_profile",
        "btn_edit_profile",
    ]
    message_ctx = MessageContext(incoming, messenger_client)

    if field_key == "name":
        err = validate_name(text, texts=validator_texts)
        if err is not None:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=err,
                keyboard=flow_keyboard_remove(),
            )
            return False
        await user_role_service.set_user(
            external_id=str(external_id_raw),
            messenger_type=incoming.user.messenger_type,
            username=text,
        )
        await state_store.clear()
        adv_texts = await bot_texts_service.get_many(adv_keys, locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_profile_updated", ""),
            keyboard=advertiser_menu_inline_keyboard(adv_texts),
        )
        await _send_profile(incoming, deps)
        return True

    updaters = {
        "phone": _adv_update_contact,
        "brand": _adv_update_brand,
        "site_link": _adv_update_site_link,
        "city": _adv_update_city,
        "company_activity": _adv_update_company_activity,
    }
    updater = updaters.get(field_key)
    if updater is None:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_unknown_field", ""),
        )
        return False

    updated = await updater(
        text,
        user_id,
        message_ctx,
        advertiser_registration_service,
        validator_texts=validator_texts,
    )
    if updated is None:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_profile_update_failed", ""),
        )
        return False

    await state_store.clear()
    adv_texts = await bot_texts_service.get_many(adv_keys, locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=edit_msgs.get("msg_profile_updated", ""),
        keyboard=advertiser_menu_inline_keyboard(adv_texts),
    )
    await _send_profile(incoming, deps)
    return True


async def _handle_blogger_field_update(
    incoming: IncomingMessage,
    field_key: str,
    text: str,
    deps: dict,
) -> bool:
    """Validate and update blogger field. Returns True on success."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    blogger_registration_service = deps["blogger_registration_service"]
    user_role_service = deps["user_role_service"]
    profile_service = deps["profile_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    country_repo = deps.get("country_repo")
    locale = deps.get("locale", "ru")

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    if user_id is None or not external_id_raw:
        await state_store.clear()
        return False

    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        await state_store.clear()
        return False

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    edit_msgs = await bot_texts_service.get_many(
        list(PROFILE_EDIT_MSG_KEYS), locale
    )
    profile_view_keys = [
        "btn_edit_profile",
        "btn_confirm_instagram",
        "btn_my_profile",
    ]
    message_ctx = MessageContext(incoming, messenger_client)
    max_order_price = getattr(config.market, "max_order_price", 1_000_000.0)
    user = await user_role_service.get_user_by_id(user_id)
    currency_symbol = await resolve_currency_symbol(
        user, country_repo, config.market.currency_symbol
    )

    if field_key == "nickname":
        err = validate_nickname(text, texts=validator_texts)
        if err is not None:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=err,
                keyboard=flow_keyboard_remove(),
            )
            return False
        await user_role_service.set_user(
            external_id=str(external_id_raw),
            messenger_type=incoming.user.messenger_type,
            username=text,
        )
        await state_store.clear()
        texts = await bot_texts_service.get_many(profile_view_keys, locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_name_updated", ""),
            keyboard=blogger_profile_view_inline_keyboard(
                texts, blogger.confirmed
            ),
        )
        await _send_profile(incoming, deps)
        return True

    if field_key == "city":
        # On Max, city is plain text (no miniapp/location fallback)
        updated_profile = await _blog_update_city(
            text,
            user_id,
            message_ctx,
            blogger_registration_service,
            webhook_base_url=None,
            bot_texts_service=bot_texts_service,
            config=config,
            validator_texts=validator_texts,
        )
        if updated_profile is None:
            await state_store.clear()
            return False
        await state_store.clear()
        texts = await bot_texts_service.get_many(profile_view_keys, locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_profile_updated", ""),
            keyboard=blogger_profile_view_inline_keyboard(
                texts, updated_profile.confirmed
            ),
        )
        await _send_profile(incoming, deps)
        return True

    updaters = {
        "instagram_url": lambda t, u, m, s: _blog_update_instagram(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "blogger_gender": lambda t, u, m, s: _blog_update_blogger_gender(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "birth_date": lambda t, u, m, s: _blog_update_birth_date(
            t, u, m, s, validator_texts=validator_texts
        ),
        "topics": lambda t, u, m, s: _blog_update_topics(
            t, u, m, s, validator_texts=validator_texts
        ),
        "audience_gender": lambda t, u, m, s: _blog_update_audience_gender(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "audience_age": lambda t, u, m, s: _blog_update_audience_age(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "audience_geo": lambda t, u, m, s: _blog_update_audience_geo(
            t,
            u,
            m,
            s,
            validator_texts=validator_texts,
            edit_msgs=edit_msgs,
        ),
        "price": lambda t, u, m, s: _blog_update_price(
            t,
            u,
            m,
            s,
            max_order_price,
            currency_symbol,
            validator_texts=validator_texts,
            edit_msgs=edit_msgs,
        ),
        "barter": lambda t, u, m, s: _blog_update_barter(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "work_format": lambda t, u, m, s: _blog_update_work_format(
            t, u, m, s, bot_texts_service, config, edit_msgs=edit_msgs
        ),
    }
    updater = updaters.get(field_key)
    if updater is None:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_unknown_field", ""),
        )
        return False

    updated_blogger = await updater(
        text, user_id, message_ctx, blogger_registration_service
    )
    if updated_blogger is None:
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=edit_msgs.get("msg_profile_update_failed", ""),
            keyboard=flow_keyboard_remove(),
        )
        return False

    await state_store.clear()
    texts = await bot_texts_service.get_many(profile_view_keys, locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=edit_msgs.get("msg_profile_updated", ""),
        keyboard=blogger_profile_view_inline_keyboard(
            texts, updated_blogger.confirmed
        ),
    )
    await _send_profile(incoming, deps)
    return True


@router.message(lambda m: bool(m.text and m.text.strip() == "/profile"))
async def show_profile(incoming: IncomingMessage, deps: dict[str, Any]) -> None:
    """Show current user's profile."""
    state_store = deps["state_store"]
    await state_store.clear()
    await _send_profile(incoming, deps)


@router.callback(lambda c: c.data == CALLBACK_PROFILE_AGREE)
async def handle_profile_agree_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Confirm agreement from profile view and show profile."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    blogger_registration_service = deps["blogger_registration_service"]
    advertiser_registration_service = deps["advertiser_registration_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    current = await state_store.get_state()
    if current not in (_BLOGGER_AGREEMENTS_STATE, _ADVERTISER_AGREEMENTS_STATE):
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        msg_expired = await bot_texts_service.get(
            "msg_session_expired_profile", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    # Confirm agreements for ALL profiles the user has to avoid an infinite
    # loop when both blogger and advertiser profiles exist: _send_profile
    # checks both via OR, but state can only encode one profile type.
    if current == _BLOGGER_AGREEMENTS_STATE:
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=None,
        )
    else:
        await advertiser_registration_service.confirm_advertiser_agreement(
            user_id=user_id,
        )

    # Also confirm the other profile if it exists
    profile_service = deps["profile_service"]
    blogger = await profile_service.get_blogger_profile(user_id)
    advertiser = await profile_service.get_advertiser_profile(user_id)
    if (
        current == _BLOGGER_AGREEMENTS_STATE
        and advertiser is not None
        and advertiser.agreement_confirmed_at is None
    ):
        await advertiser_registration_service.confirm_advertiser_agreement(
            user_id=user_id,
        )
    elif (
        current == _ADVERTISER_AGREEMENTS_STATE
        and blogger is not None
        and blogger.agreement_confirmed_at is None
    ):
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=None,
        )

    await state_store.clear()

    fake_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    await _send_profile(fake_msg, deps)


@router.callback(lambda c: c.data == CALLBACK_PROFILE_MY_PROFILE)
async def handle_profile_my_profile_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Show profile from inline button."""
    messenger_client = deps["messenger_client"]
    state_store = deps["state_store"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await state_store.clear()

    fake_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    await _send_profile(fake_msg, deps)


@router.callback(lambda c: c.data == CALLBACK_PROFILE_EDIT)
async def handle_profile_edit_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Start edit profile flow from inline button."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    profile_service = deps["profile_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    if incoming.user is None or not incoming.user.external_id:
        return

    user = await profile_service.get_user_by_external(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None:
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found_role", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_found,
        )
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if blogger is None and advertiser is None:
        msg_incomplete = await bot_texts_service.get(
            "msg_profile_incomplete", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_incomplete,
        )
        return

    await state_store.update_data(
        edit_user_id=str(user.user_id),
        edit_external_id=str(incoming.user.external_id),
    )

    if blogger is not None and advertiser is not None:
        type_texts = await bot_texts_service.get_many(
            [
                "btn_edit_profile_blogger",
                "btn_edit_profile_advertiser",
                "btn_my_profile",
                "msg_choose_profile_edit",
            ],
            locale,
        )
        msg_choose = type_texts.get("msg_choose_profile_edit", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
            keyboard=edit_profile_type_inline_keyboard(type_texts),
        )
        await state_store.set_state(_STATE_CHOOSING_PROFILE_TYPE)
        return

    if blogger is not None:
        await state_store.update_data(edit_profile_type="blogger")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_BLOGGER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_section,
            keyboard=edit_field_inline_keyboard(
                _edit_field_rows("blogger", field_texts), field_texts
            ),
        )
        await state_store.set_state(_STATE_CHOOSING_FIELD)
        return

    await state_store.update_data(edit_profile_type="advertiser")
    field_texts = await bot_texts_service.get_many(
        ["btn_my_profile", "msg_choose_section_edit"]
        + EDIT_FIELD_LABEL_KEYS_ADVERTISER,
        locale,
    )
    msg_section = field_texts.get("msg_choose_section_edit", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_section,
        keyboard=edit_field_inline_keyboard(
            _edit_field_rows("advertiser", field_texts), field_texts
        ),
    )
    await state_store.set_state(_STATE_CHOOSING_FIELD)


@router.callback(
    lambda c: (
        c.data
        in (
            CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
            CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
        )
    )
)
async def handle_profile_edit_type_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle choice of blogger or advertiser profile to edit."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    if incoming.data == CALLBACK_PROFILE_EDIT_TYPE_BLOGGER:
        await state_store.update_data(edit_profile_type="blogger")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_BLOGGER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_section,
            keyboard=edit_field_inline_keyboard(
                _edit_field_rows("blogger", field_texts), field_texts
            ),
        )
    else:
        await state_store.update_data(edit_profile_type="advertiser")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_ADVERTISER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_section,
            keyboard=edit_field_inline_keyboard(
                _edit_field_rows("advertiser", field_texts), field_texts
            ),
        )
    await state_store.set_state(_STATE_CHOOSING_FIELD)


@router.callback(
    lambda c: bool(
        c.data
        and c.data.startswith(CALLBACK_PROFILE_EDIT_FIELD_PREFIX)
        and len(c.data) > len(CALLBACK_PROFILE_EDIT_FIELD_PREFIX)
    )
)
async def handle_profile_edit_field_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle field choice from inline and ask for new value."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")
    config = deps["config"]

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    data = await state_store.get_data()
    profile_type = data.get("edit_profile_type", "blogger")
    field_key = (incoming.data or "").replace(
        CALLBACK_PROFILE_EDIT_FIELD_PREFIX, ""
    )
    if not field_key:
        return

    field_keys_set = (
        set(EDIT_FIELD_KEYS_ADVERTISER.values())
        if profile_type == "advertiser"
        else set(EDIT_FIELD_KEYS.values())
    )
    if field_key not in field_keys_set:
        return

    await state_store.update_data(editing_field=field_key)

    currency_symbol = config.market.currency_symbol
    prompt_key = "prompt_edit_" + field_key
    prompt_keys = list(
        set(PROMPT_EDIT_KEYS_BLOGGER + PROMPT_EDIT_KEYS_ADVERTISER)
        | {PROMPT_EDIT_GENERIC, prompt_key}
    )
    prompt_texts = await bot_texts_service.get_many(prompt_keys, locale)
    prompt = (
        prompt_texts.get(prompt_key)
        or prompt_texts.get(PROMPT_EDIT_GENERIC, "")
    ).format(currency=currency_symbol)

    edit_keys = [
        "btn_audience_f",
        "btn_audience_m",
        "btn_audience_a",
        "btn_gender_m",
        "btn_gender_f",
        "btn_age_0_17",
        "btn_age_18_24",
        "btn_age_25_34",
        "btn_age_35_44",
        "btn_age_45_99",
        "btn_barter_yes",
        "btn_barter_no",
        "btn_work_format_ads",
        "btn_work_format_ugc_only",
        "btn_phone_request",
        "btn_location_request",
    ]
    edit_texts = await bot_texts_service.get_many(edit_keys, locale)
    reply_markup = _get_edit_field_keyboard(field_key, profile_type, edit_texts)

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=prompt,
        keyboard=reply_markup,
    )
    await state_store.set_state(_STATE_ENTERING_VALUE)


@router.callback_in_state(
    _STATE_ENTERING_VALUE,
    lambda c: c.data in _PROFILE_CHOICE_CALLBACKS,
)
async def handle_profile_edit_choice_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle choice field value from inline (audience_gender, barter, etc.)."""
    messenger_client = deps["messenger_client"]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    locale = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    choice_keys = list(_CALLBACK_TO_CHOICE_KEY.values()) + [
        "btn_work_format_ads",
        "btn_work_format_ugc_only",
    ]
    choice_texts = await bot_texts_service.get_many(choice_keys, locale)
    choice_map = {
        cb: choice_texts.get(key, "")
        for cb, key in _CALLBACK_TO_CHOICE_KEY.items()
    }
    choice_map[CALLBACK_PROFILE_WORK_ADS] = choice_texts.get(
        "btn_work_format_ads", ""
    )
    choice_map[CALLBACK_PROFILE_WORK_UGC] = choice_texts.get(
        "btn_work_format_ugc_only", ""
    )

    data = await state_store.get_data()
    field_key = data.get("editing_field")
    profile_type = data.get("edit_profile_type", "blogger")

    if not field_key or profile_type != "blogger":
        return

    choice_text = choice_map.get(incoming.data or "")
    if not choice_text:
        return

    # Build a fake IncomingMessage for _handle_blogger_field_update
    fake_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=choice_text,
        message_id=incoming.message_id,
    )
    await _handle_blogger_field_update(fake_msg, field_key, choice_text, deps)


@router.message_in_state(_STATE_ENTERING_VALUE)
async def handle_profile_edit_value(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle free-text value for profile field edit."""
    state_store = deps["state_store"]

    data = await state_store.get_data()
    field_key = data.get("editing_field")
    profile_type = data.get("edit_profile_type", "blogger")

    if not field_key:
        await state_store.clear()
        return

    if field_key == "phone":
        text = (incoming.contact_phone or incoming.text or "").strip()
    elif (
        field_key == "city"
        and incoming.location_lat is not None
        and incoming.location_lon is not None
    ):
        from ugc_bot.application.geography import normalize_geo_token
        from ugc_bot.application.services.blogger_registration_service import (
            BloggerRegistrationService,
        )

        blogger_reg: BloggerRegistrationService = deps[
            "blogger_registration_service"
        ]
        result = await blogger_reg.resolve_city_from_location(
            incoming.location_lat, incoming.location_lon
        )
        if result is not None:
            city_from_geo, _region, _country = result
            text = normalize_geo_token(city_from_geo) or ""
        else:
            messenger_client = deps["messenger_client"]
            bot_texts_service = deps["bot_texts_service"]
            locale = deps.get("locale", "ru")
            err_loc = await bot_texts_service.get(
                "err_city_from_location", locale
            )
            loc_texts = await bot_texts_service.get_many(
                ["btn_location_request"], locale
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=err_loc,
                keyboard=flow_inline_keyboard_location_request(loc_texts),
            )
            return
    else:
        text = (incoming.text or "").strip()

    if profile_type == "advertiser":
        await _handle_advertiser_field_update(incoming, field_key, text, deps)
    else:
        await _handle_blogger_field_update(incoming, field_key, text, deps)
