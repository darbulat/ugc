"""Profile view and edit handlers."""

import json
import logging
import re
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.geography import (
    get_regions_for_city,
    normalize_geo_token,
    region_key_to_label,
)
from ugc_bot.application.messenger.context import MessageContext
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.geocoder import wkt_multipoint_from_lat_lon
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
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
    CALLBACK_PROFILE_REGION_PREFIX,
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
    flow_inline_keyboard,
    flow_keyboard_city_request,
    flow_keyboard_phone_request,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    parse_user_id_from_state,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
    VALIDATOR_ERR_KEYS,
    normalize_instagram_url,
    validate_audience_geo,
    validate_birth_date,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_name,
    validate_nickname,
    validate_phone,
    validate_price,
    validate_site_link,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)

router = Router()

# FSM state ids for agreement step (must match blogger/advertiser registration).
_BLOGGER_AGREEMENTS_STATE = "BloggerRegistrationStates:agreements"
_ADVERTISER_AGREEMENTS_STATE = "AdvertiserRegistrationStates:agreements"

PROFILE_DISPLAY_KEYS = (
    "lbl_profile_your",
    "lbl_profile_general",
    "lbl_profile_name",
    "lbl_profile_roles",
    "lbl_profile_status",
    "lbl_profile_blogger",
    "lbl_profile_not_filled",
    "lbl_profile_advertiser",
    "lbl_status_new",
    "lbl_status_active",
    "lbl_status_pause",
    "lbl_status_blocked",
    "lbl_audience_male",
    "lbl_audience_female",
    "lbl_audience_all",
    "lbl_blogger_gender_male",
    "lbl_blogger_gender_female",
    "lbl_role_blogger",
    "lbl_role_advertiser",
    "lbl_yes",
    "lbl_no",
    "lbl_work_format_ads",
    "lbl_work_format_ugc",
    "lbl_instagram",
    "lbl_confirmed",
    "lbl_city",
    "lbl_country",
    "lbl_gender",
    "lbl_birth_date",
    "lbl_topics",
    "lbl_audience",
    "lbl_geo",
    "lbl_price",
    "lbl_barter",
    "lbl_work_format",
    "lbl_phone",
    "lbl_brand",
    "lbl_activity",
    "lbl_site",
    "lbl_years",
)

_STATUS_KEY: dict[UserStatus, str] = {
    UserStatus.NEW: "lbl_status_new",
    UserStatus.ACTIVE: "lbl_status_active",
    UserStatus.PAUSE: "lbl_status_pause",
    UserStatus.BLOCKED: "lbl_status_blocked",
}
_AUDIENCE_KEY: dict[AudienceGender, str] = {
    AudienceGender.MALE: "lbl_audience_male",
    AudienceGender.FEMALE: "lbl_audience_female",
    AudienceGender.ALL: "lbl_audience_all",
}
_BLOGGER_GENDER_KEY: dict[BloggerGender, str] = {
    BloggerGender.MALE: "lbl_blogger_gender_male",
    BloggerGender.FEMALE: "lbl_blogger_gender_female",
}


def _format_profile_text(
    user: User,
    blogger: BloggerProfile | None,
    advertiser: AdvertiserProfile | None,
    currency_symbol: str = "₽",
    texts: dict[str, str] | None = None,
) -> str:
    """Format profile data for user-friendly display."""
    t = texts or {}
    roles: list[str] = []
    if blogger is not None:
        roles.append(t.get("lbl_role_blogger", "—"))
    if advertiser is not None:
        roles.append(t.get("lbl_role_advertiser", "—"))
    if not roles:
        roles.append("—")

    status_label = t.get(
        _STATUS_KEY.get(user.status, "lbl_status_active"), user.status.value
    )
    name_display = user.username or "—"

    lines = [
        t.get("lbl_profile_your", ""),
        "",
        t.get("lbl_profile_general", ""),
        f"   {t.get('lbl_profile_name', '')}: {name_display}",
        f"   {t.get('lbl_profile_roles', '')}: {', '.join(roles)}",
        f"   {t.get('lbl_profile_status', '')}: {status_label}",
    ]

    if blogger is None:
        lines.extend(
            [
                "",
                t.get("lbl_profile_blogger", ""),
                f"   {t.get('lbl_profile_not_filled', '')}",
            ]
        )
    else:
        topics = ", ".join(blogger.topics.get("selected", [])) or "—"
        confirmed = (
            t.get("lbl_yes", "Да")
            if blogger.confirmed
            else t.get("lbl_no", "Нет")
        )
        barter_str = (
            t.get("lbl_yes", "Да") if blogger.barter else t.get("lbl_no", "Нет")
        )
        work_fmt = (
            t.get("lbl_work_format_ads", "")
            if blogger.work_format == WorkFormat.ADS_IN_ACCOUNT
            else t.get("lbl_work_format_ugc", "")
        )
        gender_label = t.get(
            _AUDIENCE_KEY.get(blogger.audience_gender, "lbl_audience_all"),
            blogger.audience_gender.value,
        )
        blogger_gender_label = "—"
        if blogger.blogger_gender is not None:
            blogger_gender_label = t.get(
                _BLOGGER_GENDER_KEY.get(
                    blogger.blogger_gender, BloggerGender.MALE
                ),
                blogger.blogger_gender.value,
            )
        birth_date_str = (
            blogger.birth_date.strftime("%d.%m.%Y")
            if blogger.birth_date is not None
            else "—"
        )
        years = t.get("lbl_years", "лет")
        lines.extend(
            [
                "",
                t.get("lbl_profile_blogger", ""),
                f"   {t.get('lbl_instagram', '')}: {blogger.instagram_url}",
                f"   {t.get('lbl_confirmed', '')}: {confirmed}",
                f"   {t.get('lbl_city', '')}: {blogger.city}",
                f"   {t.get('lbl_country', '')}: {blogger.country}",
                f"   {t.get('lbl_gender', '')}: {blogger_gender_label}",
                f"   {t.get('lbl_birth_date', '')}: {birth_date_str}",
                f"   {t.get('lbl_topics', '')}: {topics}",
                f"   {t.get('lbl_audience', '')}: {gender_label}, "
                f"{blogger.audience_age_min}–{blogger.audience_age_max} "
                f"{years}",
                f"   {t.get('lbl_geo', '')}: {blogger.audience_geo}",
                f"   {t.get('lbl_price', '')}: {blogger.price} "
                f"{currency_symbol}",
                f"   {t.get('lbl_barter', '')}: {barter_str}",
                f"   {t.get('lbl_work_format', '')}: {work_fmt}",
            ]
        )

    if advertiser is None:
        lines.extend(
            [
                "",
                t.get("lbl_profile_advertiser", ""),
                f"   {t.get('lbl_profile_not_filled', '')}",
            ]
        )
    else:
        adv_lines = [
            "",
            t.get("lbl_profile_advertiser", ""),
            f"   {t.get('lbl_phone', '')}: {advertiser.phone}",
            f"   {t.get('lbl_brand', '')}: {advertiser.brand}",
        ]
        if advertiser.city:
            adv_lines.append(f"   {t.get('lbl_city', '')}: {advertiser.city}")
        if advertiser.company_activity:
            adv_lines.append(
                f"   {t.get('lbl_activity', '')}: {advertiser.company_activity}"
            )
        if advertiser.site_link:
            adv_lines.append(
                f"   {t.get('lbl_site', '')}: {advertiser.site_link}"
            )
        lines.extend(adv_lines)

    return "\n".join(lines)


logger = logging.getLogger(__name__)

INSTAGRAM_URL_REGEX = re.compile(
    r"^(https?://)?(www\.)?instagram\.com/[A-Za-z0-9._]+/?$"
)

_EDIT_FIELDS_BY_KEY = [
    ("lbl_edit_nickname", "nickname"),
    ("lbl_edit_instagram", "instagram_url"),
    ("lbl_edit_city", "city"),
    ("lbl_edit_blogger_gender", "blogger_gender"),
    ("lbl_edit_birth_date", "birth_date"),
    ("lbl_edit_topics", "topics"),
    ("lbl_edit_audience_gender", "audience_gender"),
    ("lbl_edit_audience_age", "audience_age"),
    ("lbl_edit_audience_geo", "audience_geo"),
    ("lbl_edit_price", "price"),
    ("lbl_edit_barter", "barter"),
    ("lbl_edit_work_format", "work_format"),
]
_EDIT_FIELDS_ADVERTISER_BY_KEY = [
    ("lbl_edit_name", "name"),
    ("lbl_edit_phone", "phone"),
    ("lbl_edit_city", "city"),
    ("lbl_edit_brand", "brand"),
    ("lbl_edit_company_activity", "company_activity"),
    ("lbl_edit_site_link", "site_link"),
]
EDIT_FIELD_KEYS = {label_key: fkey for label_key, fkey in _EDIT_FIELDS_BY_KEY}
EDIT_FIELD_KEYS_ADVERTISER = {
    label_key: fkey for label_key, fkey in _EDIT_FIELDS_ADVERTISER_BY_KEY
}
EDIT_FIELD_LABEL_KEYS_BLOGGER = [lk for lk, _ in _EDIT_FIELDS_BY_KEY]
EDIT_FIELD_LABEL_KEYS_ADVERTISER = [
    lk for lk, _ in _EDIT_FIELDS_ADVERTISER_BY_KEY
]
PROMPT_EDIT_KEYS_BLOGGER = [
    "prompt_edit_nickname",
    "prompt_edit_instagram_url",
    "prompt_edit_city",
    "prompt_edit_blogger_gender",
    "prompt_edit_birth_date",
    "prompt_edit_topics",
    "prompt_edit_audience_gender",
    "prompt_edit_audience_age",
    "prompt_edit_audience_geo",
    "prompt_edit_price",
    "prompt_edit_barter",
    "prompt_edit_work_format",
]
PROMPT_EDIT_KEYS_ADVERTISER = [
    "prompt_edit_name",
    "prompt_edit_phone",
    "prompt_edit_city",
    "prompt_edit_brand",
    "prompt_edit_company_activity",
    "prompt_edit_site_link",
]
PROMPT_EDIT_GENERIC = "prompt_edit_generic"
PROFILE_EDIT_MSG_KEYS = [
    "msg_profile_updated",
    "msg_unknown_field",
    "msg_profile_update_failed",
    "err_instagram_format_example",
    "err_instagram_invalid",
    "err_instagram_taken",
    "msg_city_picker_edit",
    "err_gender_choose",
    "lbl_blogger_gender_male",
    "lbl_blogger_gender_female",
    "msg_choose_buttons",
    "err_age_choose",
    "err_geo_max_cities",
    "msg_enter_number",
    "err_barter_choose",
    "lbl_yes",
    "lbl_no",
    "msg_city_multiple_regions",
    "msg_name_updated",
    "btn_audience_f",
    "btn_audience_m",
    "btn_audience_a",
    "btn_age_0_17",
    "btn_age_18_24",
    "btn_age_25_34",
    "btn_age_35_44",
    "btn_age_45_99",
]

_AGE_BUTTONS: dict[str, tuple[int, int]] = {
    "до 18": (1, 17),
    "18–24": (18, 24),
    "25–34": (25, 34),
    "35–44": (35, 44),
    "45+": (45, 99),
}


EDIT_PROFILE_FLOW_TYPE = "edit_profile"


async def _adv_update_contact(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> AdvertiserProfile | None:
    """Update phone. Returns profile or None."""
    err = validate_phone(text, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, phone=text
    )


async def _adv_update_brand(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> AdvertiserProfile | None:
    """Update brand. Returns profile or None."""
    err = validate_brand(text, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, brand=text
    )


async def _adv_update_site_link(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> AdvertiserProfile | None:
    """Update site_link. Returns profile or None."""
    err = validate_site_link(text or None, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, site_link=text or None
    )


async def _adv_update_city(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> AdvertiserProfile | None:
    """Update city. Returns profile or None."""
    err = validate_city(text or None, required=False, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, city=text or None
    )


async def _adv_update_company_activity(
    text: str,
    user_id: UUID,
    message: MessageContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> AdvertiserProfile | None:
    """Update company_activity. Returns profile or None."""
    err = validate_company_activity(text or None, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await advertiser_registration_service.update_advertiser_profile(
        user_id, company_activity=text or None
    )


async def _update_advertiser_field(
    message: MessageContext,
    state: FSMContext,
    field_key: str,
    text: str,
    user_id: UUID,
    external_id: str,
    advertiser: AdvertiserProfile,
    profile_service: ProfileService,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
) -> bool:
    """Validate and update advertiser field. Returns True on success."""
    locale = config.market.default_locale
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
    if field_key == "name":
        err = validate_name(text, texts=validator_texts)
        if err is not None:
            await message.answer(err, reply_markup=flow_keyboard_remove())
            return False
        await user_role_service.set_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=text,
        )
        await state.clear()
        adv_texts = await bot_texts_service.get_many(adv_keys, locale)
        msg_updated = edit_msgs.get("msg_profile_updated", "")
        await message.answer(
            msg_updated,
            reply_markup=advertiser_menu_inline_keyboard(adv_texts),
        )
        await show_profile(
            message, profile_service, state, config, bot_texts_service
        )
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
        await state.clear()
        await message.answer(edit_msgs.get("msg_unknown_field", ""))
        return False
    updated = await updater(
        text,
        user_id,
        message,
        advertiser_registration_service,
        validator_texts=validator_texts,
    )
    if updated is None:
        await state.clear()
        await message.answer(edit_msgs.get("msg_profile_update_failed", ""))
        return False
    await state.clear()
    adv_texts = await bot_texts_service.get_many(adv_keys, locale)
    await message.answer(
        edit_msgs.get("msg_profile_updated", ""),
        reply_markup=advertiser_menu_inline_keyboard(adv_texts),
    )
    await show_profile(
        message, profile_service, state, config, bot_texts_service
    )
    return True


async def _blog_update_instagram(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update instagram_url. Returns profile or None."""
    em = edit_msgs or {}
    if not text or "instagram.com/" not in text.lower():
        await message.answer(em.get("err_instagram_format_example", ""))
        return None
    text = normalize_instagram_url(text)
    if not INSTAGRAM_URL_REGEX.match(text):
        await message.answer(em.get("err_instagram_invalid", ""))
        return None
    existing = await blogger_registration_service.get_profile_by_instagram_url(
        text
    )
    if existing is not None and existing.user_id != user_id:
        await message.answer(em.get("err_instagram_taken", ""))
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, instagram_url=text
    )


async def _blog_update_city(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    webhook_base_url: str | None = None,
    bot_texts_service: BotTextsService | None = None,
    config: AppConfig | None = None,
    validator_texts: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update city. Returns profile or None. Accepts any city text."""
    err = validate_city(text, required=True, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    normalized = normalize_geo_token(text)
    if not normalized:
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, city=normalized
    )


async def _blog_update_topics(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update topics. Returns profile or None."""
    topics = [t.strip().lower() for t in text.split(",") if t.strip()]
    err = validate_topics(topics, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, topics={"selected": topics}
    )


async def _blog_update_blogger_gender(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update blogger_gender. Returns profile or None."""
    em = edit_msgs or {}
    male_label = (em.get("lbl_blogger_gender_male") or "Мужской").strip()
    female_label = (em.get("lbl_blogger_gender_female") or "Женский").strip()
    if text.strip() == male_label:
        blogger_gender = BloggerGender.MALE
    elif text.strip() == female_label:
        blogger_gender = BloggerGender.FEMALE
    else:
        await message.answer(em.get("err_gender_choose", ""))
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, blogger_gender=blogger_gender
    )


async def _blog_update_birth_date(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    validator_texts: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update birth_date. Returns profile or None."""
    parsed_date, err = validate_birth_date(text, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    assert parsed_date is not None
    return await blogger_registration_service.update_blogger_profile(
        user_id, birth_date=parsed_date
    )


async def _blog_update_audience_gender(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update audience_gender. Returns profile or None."""
    em = edit_msgs or {}
    text_stripped = text.strip()
    if text_stripped == (em.get("btn_audience_f") or "").strip():
        audience_gender = AudienceGender.FEMALE
    elif text_stripped == (em.get("btn_audience_m") or "").strip():
        audience_gender = AudienceGender.MALE
    elif text_stripped == (em.get("btn_audience_a") or "").strip():
        audience_gender = AudienceGender.ALL
    else:
        await message.answer(em.get("msg_choose_buttons", ""))
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_gender=audience_gender
    )


def _age_buttons_from_edit_msgs(
    edit_msgs: dict[str, str],
) -> dict[str, tuple[int, int]]:
    """Build age label -> (min, max) from edit_msgs button labels."""
    return {
        (edit_msgs.get("btn_age_0_17") or "до 18").strip(): (1, 17),
        (edit_msgs.get("btn_age_18_24") or "18–24").strip(): (18, 24),
        (edit_msgs.get("btn_age_25_34") or "25–34").strip(): (25, 34),
        (edit_msgs.get("btn_age_35_44") or "35–44").strip(): (35, 44),
        (edit_msgs.get("btn_age_45_99") or "45+").strip(): (45, 99),
    }


async def _blog_update_audience_age(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update audience_age. Returns profile or None."""
    em = edit_msgs or {}
    age_map = _age_buttons_from_edit_msgs(em) if em else _AGE_BUTTONS
    text_stripped = text.strip()
    if text_stripped not in age_map:
        await message.answer(em.get("err_age_choose", ""))
        return None
    min_age, max_age = age_map[text_stripped]
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_age_min=min_age, audience_age_max=max_age
    )


async def _blog_update_audience_geo(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    validator_texts: dict[str, str] | None = None,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update audience_geo. Returns profile or None."""
    em = edit_msgs or {}
    err = validate_audience_geo(text, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    cities = [c.strip() for c in text.split(",") if c.strip()]
    if len(cities) > 3:
        await message.answer(
            em.get("err_geo_max_cities", ""),
            reply_markup=flow_keyboard_remove(),
        )
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, audience_geo=text
    )


async def _blog_update_price(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    max_order_price: float,
    currency_symbol: str = "₽",
    validator_texts: dict[str, str] | None = None,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update price. Returns profile or None."""
    em = edit_msgs or {}
    try:
        price = float(text.replace(",", "."))
    except ValueError:
        await message.answer(em.get("msg_enter_number", ""))
        return None
    err = validate_price(
        price, max_order_price, currency_symbol, texts=validator_texts
    )
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, price=price
    )


async def _blog_update_barter(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update barter. Returns profile or None."""
    em = edit_msgs or {}
    yes_label = (em.get("lbl_yes") or "Да").strip().lower()
    no_label = (em.get("lbl_no") or "Нет").strip().lower()
    if text.strip().lower() == yes_label:
        barter = True
    elif text.strip().lower() == no_label:
        barter = False
    else:
        await message.answer(em.get("err_barter_choose", ""))
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, barter=barter
    )


async def _blog_update_work_format(
    text: str,
    user_id: UUID,
    message: MessageContext,
    blogger_registration_service: BloggerRegistrationService,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    edit_msgs: dict[str, str] | None = None,
) -> BloggerProfile | None:
    """Update work_format. Returns profile or None."""
    locale = config.market.default_locale
    btn_ads = (
        await bot_texts_service.get("btn_work_format_ads", locale)
    ).strip()
    btn_ugc = (
        await bot_texts_service.get("btn_work_format_ugc_only", locale)
    ).strip()
    em = edit_msgs or {}
    if text.strip() == btn_ads:
        wf = WorkFormat.ADS_IN_ACCOUNT
    elif text.strip() == btn_ugc:
        wf = WorkFormat.UGC_ONLY
    else:
        await message.answer(em.get("msg_choose_buttons", ""))
        return None
    return await blogger_registration_service.update_blogger_profile(
        user_id, work_format=wf
    )


async def _update_blogger_field_city(
    message: MessageContext,
    state: FSMContext,
    text: str,
    user_id: UUID,
    blogger_registration_service: BloggerRegistrationService,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
) -> bool | None:
    """
    Handle city field update: validate, maybe region picker, or save.
    Returns True/False on done; None if not handled (call updater).
    """
    locale = config.market.default_locale
    edit_msgs = await bot_texts_service.get_many(
        list(PROFILE_EDIT_MSG_KEYS), locale
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    err = validate_city(text, required=True, texts=validator_texts)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return False
    normalized = normalize_geo_token(text)
    if not normalized:
        await message.answer(
            edit_msgs.get("msg_profile_update_failed", ""),
            reply_markup=flow_keyboard_remove(),
        )
        return False
    regions = get_regions_for_city(normalized)
    if len(regions) > 1:
        await state.update_data(pending_city_edit=normalized)
        region_buttons = [
            [
                Button(
                    text=region_key_to_label(r),
                    callback_data=f"{CALLBACK_PROFILE_REGION_PREFIX}{r}",
                )
            ]
            for r in regions
        ]
        await message.answer(
            edit_msgs.get("msg_city_multiple_regions", ""),
            reply_markup=flow_inline_keyboard(region_buttons),
        )
        return True
    updated = await blogger_registration_service.update_blogger_profile(
        user_id,
        city=normalized,
        region=regions[0] if regions else None,
        country="Russia" if regions else None,
    )
    if updated is None:
        await state.clear()
        await message.answer(
            edit_msgs.get("msg_profile_update_failed", ""),
            reply_markup=flow_keyboard_remove(),
        )
        return False
    await state.clear()
    await message.answer(
        edit_msgs.get("msg_profile_updated", ""),
        reply_markup=flow_keyboard_remove(),
    )
    await show_profile(
        message, profile_service, state, config, bot_texts_service
    )
    return True


async def _update_blogger_field(
    message: MessageContext,
    state: FSMContext,
    field_key: str,
    text: str,
    user_id: UUID,
    external_id: str,
    blogger: BloggerProfile,
    profile_service: ProfileService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
    config: AppConfig,
    bot_texts_service: BotTextsService,
) -> bool:
    """Validate and update blogger field. Returns True on success."""
    locale = config.market.default_locale
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
    if field_key == "nickname":
        err = validate_nickname(text, texts=validator_texts)
        if err is not None:
            await message.answer(err, reply_markup=flow_keyboard_remove())
            return False
        await user_role_service.set_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=text,
        )
        await state.clear()
        texts = await bot_texts_service.get_many(profile_view_keys, locale)
        msg_name_updated = edit_msgs.get("msg_name_updated", "")
        await message.answer(
            msg_name_updated,
            reply_markup=blogger_profile_view_inline_keyboard(
                texts, blogger.confirmed
            ),
        )
        await show_profile(
            message, profile_service, state, config, bot_texts_service
        )
        return True

    if field_key == "city":
        result = await _update_blogger_field_city(
            message,
            state,
            text,
            user_id,
            blogger_registration_service,
            profile_service,
            config,
            bot_texts_service,
        )
        if result is not None:
            return result

    updaters = {
        "instagram_url": lambda t, u, m, s: _blog_update_instagram(
            t, u, m, s, edit_msgs=edit_msgs
        ),
        "city": lambda t, u, m, s: _blog_update_city(
            t,
            u,
            m,
            s,
            config.webhook.webhook_base_url,
            bot_texts_service,
            config,
            validator_texts=validator_texts,
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
            config.market.currency_symbol,
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
        await state.clear()
        await message.answer(edit_msgs.get("msg_unknown_field", ""))
        return False
    updated_blogger = await updater(
        text, user_id, message, blogger_registration_service
    )
    if updated_blogger is None:
        await state.clear()
        await message.answer(
            edit_msgs.get("msg_profile_update_failed", ""),
            reply_markup=flow_keyboard_remove(),
        )
        return False
    await state.clear()
    texts = await bot_texts_service.get_many(profile_view_keys, locale)
    await message.answer(
        edit_msgs.get("msg_profile_updated", ""),
        reply_markup=blogger_profile_view_inline_keyboard(
            texts, updated_blogger.confirmed
        ),
    )
    await show_profile(
        message, profile_service, state, config, bot_texts_service
    )
    return True


class EditProfileStates(StatesGroup):
    """States for editing blogger or advertiser profile."""

    choosing_profile_type = State()
    choosing_field = State()
    entering_value = State()


async def _remove_inline_keyboard_from_callback(
    incoming: IncomingCallback,
    messenger_client: MessengerClient,
) -> None:
    """Remove inline keyboard from the message that triggered the callback."""
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )


@router.message(Command("profile"))
@router.message(TextEqualsKey("btn_my_profile"))
async def show_profile(
    message: Message,
    profile_service: ProfileService,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show current user's profile or ask to confirm agreement if not yet."""
    if isinstance(message, MessageContext):
        message_ctx = message
    else:
        messenger_client, event_adapter = resolve_messenger_dependencies(
            message, messenger_client, event_adapter
        )
        incoming = event_adapter.from_message(message)
        message_ctx = MessageContext(incoming, messenger_client)
    await state.clear()

    if message_ctx.from_user is None or not message_ctx.from_user.id:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message_ctx.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    locale = config.market.default_locale
    if user is None:
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found_role", locale
        )
        await message_ctx.answer(msg_not_found)
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    agreement_confirmed_at = getattr(user, "agreement_confirmed_at", None)
    if (
        blogger is not None or advertiser is not None
    ) and agreement_confirmed_at is None:
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
        )
        await message_ctx.answer(
            agreements_text,
            reply_markup=confirm_agreement_inline_keyboard(
                CALLBACK_PROFILE_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state.update_data(user_id=user.user_id)
        if blogger is not None:
            await state.set_state(_BLOGGER_AGREEMENTS_STATE)
        else:
            await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    profile_texts = await bot_texts_service.get_many(
        list(PROFILE_DISPLAY_KEYS), locale
    )
    text = _format_profile_text(
        user,
        blogger,
        advertiser,
        config.market.currency_symbol,
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

    await message_ctx.answer(text, reply_markup=reply_markup)


@router.callback_query(lambda c: c.data == CALLBACK_PROFILE_AGREE)
async def handle_profile_agree_callback(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    user_role_service: UserRoleService,
    blogger_registration_service: BloggerRegistrationService,
    advertiser_registration_service: AdvertiserRegistrationService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    currency_symbol: str,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Confirm agreement from profile view (inline) and show profile."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    current = await state.get_state()
    if current not in (_BLOGGER_AGREEMENTS_STATE, _ADVERTISER_AGREEMENTS_STATE):
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        locale = config.market.default_locale
        msg_expired = await bot_texts_service.get(
            "msg_session_expired_profile", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state.clear()
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    if current == _BLOGGER_AGREEMENTS_STATE:
        telegram_username = getattr(incoming.user, "username", None)
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=telegram_username,
        )
    else:
        await advertiser_registration_service.confirm_advertiser_agreement(
            user_id=user_id,
        )
    await state.clear()
    user = await user_role_service.get_user_by_id(user_id)
    locale = config.market.default_locale
    if user is None:
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_found,
        )
        return
    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    profile_texts = await bot_texts_service.get_many(
        list(PROFILE_DISPLAY_KEYS), locale
    )
    text = _format_profile_text(
        user,
        blogger,
        advertiser,
        currency_symbol=currency_symbol,
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


@router.callback_query(lambda c: c.data == CALLBACK_PROFILE_EDIT)
async def handle_profile_edit_callback(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start edit profile flow from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    if incoming.user is None or not incoming.user.external_id:
        return
    locale = config.market.default_locale
    user = await profile_service.get_user_by_external(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.TELEGRAM,
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
    await state.update_data(
        edit_user_id=user.user_id,
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
        await state.set_state(EditProfileStates.choosing_profile_type)
        return
    if blogger is not None:
        await state.update_data(edit_profile_type="blogger")
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
        await state.set_state(EditProfileStates.choosing_field)
        return
    await state.update_data(edit_profile_type="advertiser")
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
    await state.set_state(EditProfileStates.choosing_field)


@router.callback_query(lambda c: c.data == CALLBACK_PROFILE_MY_PROFILE)
async def handle_profile_my_profile_callback(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show profile from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await state.clear()
    locale = config.market.default_locale
    if incoming.user is None or not incoming.user.external_id:
        return
    external_id = incoming.user.external_id
    user = await profile_service.get_user_by_external(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
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
    agreement_confirmed_at = getattr(user, "agreement_confirmed_at", None)
    if (
        blogger is not None or advertiser is not None
    ) and agreement_confirmed_at is None:
        locale = config.market.default_locale
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
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=confirm_agreement_inline_keyboard(
                CALLBACK_PROFILE_AGREE, agree_texts
            ),
            parse_mode="HTML",
        )
        await state.update_data(user_id=user.user_id)
        if blogger is not None:
            await state.set_state(_BLOGGER_AGREEMENTS_STATE)
        else:
            await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return
    locale = config.market.default_locale
    profile_texts = await bot_texts_service.get_many(
        list(PROFILE_DISPLAY_KEYS), locale
    )
    text = _format_profile_text(
        user,
        blogger,
        advertiser,
        config.market.currency_symbol,
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


@router.callback_query(
    lambda c: (
        c.data
        in (
            CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
            CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
        )
    )
)
async def handle_profile_edit_type_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    profile_service: ProfileService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle choice of blogger or advertiser profile to edit (inline)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    locale = config.market.default_locale
    if incoming.data == CALLBACK_PROFILE_EDIT_TYPE_BLOGGER:
        await state.update_data(edit_profile_type="blogger")
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
        await state.update_data(edit_profile_type="advertiser")
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
    await state.set_state(EditProfileStates.choosing_field)


@router.callback_query(
    lambda c: (
        c.data
        and c.data.startswith(CALLBACK_PROFILE_EDIT_FIELD_PREFIX)
        and len(c.data or "") > len(CALLBACK_PROFILE_EDIT_FIELD_PREFIX)
    )
)
async def handle_profile_edit_field_callback(  # noqa: C901
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle field choice from inline and ask for new value."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    data = await state.get_data()
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
    await state.update_data(editing_field=field_key)
    fake_message = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    message_ctx = MessageContext(fake_message, messenger_client)
    locale = config.market.default_locale
    prompt_key = "prompt_edit_" + field_key
    prompt_keys = list(
        set(PROMPT_EDIT_KEYS_BLOGGER + PROMPT_EDIT_KEYS_ADVERTISER)
        | {PROMPT_EDIT_GENERIC, prompt_key}
    )
    prompt_texts = await bot_texts_service.get_many(prompt_keys, locale)
    prompt = prompt_texts.get(prompt_key) or prompt_texts.get(
        PROMPT_EDIT_GENERIC, ""
    )
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
        "btn_location_map",
    ]
    edit_texts = await bot_texts_service.get_many(edit_keys, locale)
    if field_key == "audience_gender":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_audience_gender_inline_keyboard(edit_texts),
        )
    elif field_key == "blogger_gender":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_blogger_gender_inline_keyboard(edit_texts),
        )
    elif field_key == "audience_age":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_audience_age_inline_keyboard(edit_texts),
        )
    elif field_key == "barter":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_barter_inline_keyboard(edit_texts),
        )
    elif field_key == "work_format":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_work_format_inline_keyboard(edit_texts),
        )
    elif field_key == "city" and profile_type == "blogger":
        miniapp_url = None
        base = getattr(config.webhook, "webhook_base_url", None) or ""
        if base:
            miniapp_url = base.rstrip("/") + "/miniapp/location_picker.html"
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard_city_request(
                edit_texts, miniapp_location_url=miniapp_url
            ),
        )
    elif field_key == "phone" and profile_type == "advertiser":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard_phone_request(edit_texts),
        )
    else:
        await message_ctx.answer(prompt, reply_markup=flow_keyboard_remove())
    await state.set_state(EditProfileStates.entering_value)


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


@router.callback_query(lambda c: c.data in _PROFILE_CHOICE_CALLBACKS)
async def handle_profile_edit_choice_callback(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle choice field value from inline (audience_gender, barter, etc.)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = config.market.default_locale
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
    data = await state.get_data()
    field_key = data.get("editing_field")
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    profile_type = data.get("edit_profile_type", "blogger")
    if (
        not field_key
        or user_id is None
        or not external_id_raw
        or profile_type != "blogger"
    ):
        return
    choice_text = choice_map.get(incoming.data or "")
    if not choice_text:
        return
    fake_message = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
        message_id=incoming.message_id,
    )
    message_ctx = MessageContext(fake_message, messenger_client)
    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        await state.clear()
        return
    await _update_blogger_field(
        message_ctx,
        state,
        field_key,
        choice_text,
        user_id,
        str(external_id_raw),
        blogger,
        profile_service,
        blogger_registration_service,
        user_role_service,
        max_order_price,
        config,
        bot_texts_service,
    )
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)


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


@router.message(TextEqualsKey("btn_edit_profile"))
async def edit_profile_start(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show field selection for profile edit."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)

    if message_ctx.from_user is None or not message_ctx.from_user.id:
        return

    user = await profile_service.get_user_by_external(
        external_id=str(message_ctx.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    locale = config.market.default_locale
    if user is None:
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found_role", locale
        )
        await message_ctx.answer(msg_not_found)
        return

    blogger = await profile_service.get_blogger_profile(user.user_id)
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if blogger is None and advertiser is None:
        msg_incomplete = await bot_texts_service.get(
            "msg_profile_incomplete", locale
        )
        await message_ctx.answer(msg_incomplete)
        return

    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id=str(message_ctx.from_user.id),
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
        await message_ctx.answer(
            msg_choose,
            reply_markup=edit_profile_type_inline_keyboard(type_texts),
        )
        await state.set_state(EditProfileStates.choosing_profile_type)
        return
    if blogger is not None:
        await state.update_data(edit_profile_type="blogger")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_BLOGGER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await message_ctx.answer(
            msg_section,
            reply_markup=edit_field_inline_keyboard(
                _edit_field_rows("blogger", field_texts), field_texts
            ),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    await state.update_data(edit_profile_type="advertiser")
    field_texts = await bot_texts_service.get_many(
        ["btn_my_profile", "msg_choose_section_edit"]
        + EDIT_FIELD_LABEL_KEYS_ADVERTISER,
        locale,
    )
    msg_section = field_texts.get("msg_choose_section_edit", "")
    await message_ctx.answer(
        msg_section,
        reply_markup=edit_field_inline_keyboard(
            _edit_field_rows("advertiser", field_texts), field_texts
        ),
    )
    await state.set_state(EditProfileStates.choosing_field)


@router.message(EditProfileStates.choosing_profile_type)
async def edit_profile_choose_type(
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle choice of blogger or advertiser profile to edit."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    text = (message_ctx.text or "").strip()
    locale = config.market.default_locale
    my_profile_btn = (
        await bot_texts_service.get("btn_my_profile", locale)
    ).strip()
    if text == my_profile_btn:
        await state.clear()
        await show_profile(
            message=message_ctx,
            profile_service=profile_service,
            state=state,
            config=config,
            bot_texts_service=bot_texts_service,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
        return
    edit_blogger_btn = (
        await bot_texts_service.get("btn_edit_profile_blogger", locale)
    ).strip()
    edit_advertiser_btn = (
        await bot_texts_service.get("btn_edit_profile_advertiser", locale)
    ).strip()
    if text == edit_blogger_btn:
        await state.update_data(edit_profile_type="blogger")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_BLOGGER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await message_ctx.answer(
            msg_section,
            reply_markup=edit_field_inline_keyboard(
                _edit_field_rows("blogger", field_texts), field_texts
            ),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    if text == edit_advertiser_btn:
        await state.update_data(edit_profile_type="advertiser")
        field_texts = await bot_texts_service.get_many(
            ["btn_my_profile", "msg_choose_section_edit"]
            + EDIT_FIELD_LABEL_KEYS_ADVERTISER,
            locale,
        )
        msg_section = field_texts.get("msg_choose_section_edit", "")
        await message_ctx.answer(
            msg_section,
            reply_markup=edit_field_inline_keyboard(
                _edit_field_rows("advertiser", field_texts), field_texts
            ),
        )
        await state.set_state(EditProfileStates.choosing_field)
        return
    type_texts = await bot_texts_service.get_many(
        [
            "btn_edit_profile_blogger",
            "btn_edit_profile_advertiser",
            "btn_my_profile",
            "msg_choose_from_keyboard",
        ],
        locale,
    )
    msg_keyboard = type_texts.get("msg_choose_from_keyboard", "")
    await message_ctx.answer(
        msg_keyboard,
        reply_markup=edit_profile_type_inline_keyboard(type_texts),
    )


@router.message(EditProfileStates.choosing_field)
async def edit_profile_choose_field(  # noqa: C901
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle field choice and ask for new value."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    text = (message_ctx.text or "").strip()
    my_profile_btn = (
        await bot_texts_service.get(
            "btn_my_profile", config.market.default_locale
        )
    ).strip()
    if text == my_profile_btn:
        await state.clear()
        await show_profile(
            message=message_ctx,
            profile_service=profile_service,
            state=state,
            config=config,
            bot_texts_service=bot_texts_service,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
        return

    data = await state.get_data()
    profile_type = data.get("edit_profile_type", "blogger")
    locale = config.market.default_locale
    field_label_keys = (
        _EDIT_FIELDS_ADVERTISER_BY_KEY
        if profile_type == "advertiser"
        else _EDIT_FIELDS_BY_KEY
    )
    prompt_keys_for_type = (
        PROMPT_EDIT_KEYS_ADVERTISER
        if profile_type == "advertiser"
        else PROMPT_EDIT_KEYS_BLOGGER
    )
    edit_keys_base = [
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
    ]
    load_keys = (
        [lk for lk, _ in field_label_keys]
        + prompt_keys_for_type
        + [
            PROMPT_EDIT_GENERIC,
            "msg_choose_section_keyboard",
            "btn_my_profile",
            "btn_phone_request",
        ]
        + edit_keys_base
    )
    field_texts = await bot_texts_service.get_many(load_keys, locale)
    field_keys_for_match = {
        field_texts.get(lk): fk for (lk, fk) in field_label_keys
    }
    if text not in field_keys_for_match:
        msg_keyboard = field_texts.get("msg_choose_section_keyboard", "")
        await message_ctx.answer(
            msg_keyboard,
            reply_markup=edit_field_inline_keyboard(
                _edit_field_rows(profile_type, field_texts), field_texts
            ),
        )
        return

    field_key = field_keys_for_match[text]
    await state.update_data(editing_field=field_key)
    prompt = field_texts.get("prompt_edit_" + field_key) or field_texts.get(
        PROMPT_EDIT_GENERIC, ""
    )
    edit_texts = field_texts
    if field_key == "audience_gender":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_audience_gender_inline_keyboard(edit_texts),
        )
    elif field_key == "blogger_gender":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_blogger_gender_inline_keyboard(edit_texts),
        )
    elif field_key == "audience_age":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_audience_age_inline_keyboard(edit_texts),
        )
    elif field_key == "barter":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_barter_inline_keyboard(edit_texts),
        )
    elif field_key == "work_format":
        await message_ctx.answer(
            prompt,
            reply_markup=edit_work_format_inline_keyboard(edit_texts),
        )
    elif field_key == "city" and profile_type == "blogger":
        miniapp_url = None
        base = getattr(config.webhook, "webhook_base_url", None) or ""
        if base:
            miniapp_url = base.rstrip("/") + "/miniapp/location_picker.html"
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard_city_request(
                edit_texts, miniapp_location_url=miniapp_url
            ),
        )
    elif field_key == "phone" and profile_type == "advertiser":
        await message_ctx.answer(
            prompt,
            reply_markup=flow_keyboard_phone_request(edit_texts),
        )
    else:
        await message_ctx.answer(prompt, reply_markup=flow_keyboard_remove())

    await state.set_state(EditProfileStates.entering_value)


@router.callback_query(
    lambda c: c.data and c.data.startswith(CALLBACK_PROFILE_REGION_PREFIX),
    StateFilter(EditProfileStates.entering_value),
)
async def handle_profile_region_callback(
    callback: CallbackQuery,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store selected region for city edit (city in multiple regions)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    data = await state.get_data()
    city = data.get("pending_city_edit")
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    if not city or user_id is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return
    region = (callback.data or "").removeprefix(CALLBACK_PROFILE_REGION_PREFIX)
    if region not in get_regions_for_city(city):
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    await blogger_registration_service.update_blogger_profile(
        user_id,
        city=city,
        region=region,
        country="Russia",
    )
    await state.clear()
    msg_updated = await bot_texts_service.get(
        "msg_profile_updated", config.market.default_locale
    )
    incoming_msg = IncomingMessage(
        chat_id=incoming.chat_id,
        user=incoming.user,
        text=None,
    )
    message_ctx = MessageContext(incoming_msg, messenger_client)
    await message_ctx.answer(
        msg_updated,
        reply_markup=flow_keyboard_remove(),
    )
    await show_profile(
        message=message_ctx,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )


@router.message(EditProfileStates.entering_value)
async def edit_profile_enter_value(  # noqa: C901
    message: Message,
    state: FSMContext,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
    max_order_price: float,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Validate and save new field value, then show profile."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    message_ctx = MessageContext(incoming, messenger_client)
    data = await state.get_data()
    field_key = data.get("editing_field")
    user_id = parse_user_id_from_state(data, key="edit_user_id")
    external_id_raw = data.get("edit_external_id")
    profile_type = data.get("edit_profile_type", "blogger")
    if not field_key or user_id is None or not external_id_raw:
        await state.clear()
        locale = config.market.default_locale
        msg_expired = await bot_texts_service.get(
            "msg_session_expired_profile", locale
        )
        await message_ctx.answer(msg_expired)
        return
    external_id = str(external_id_raw)
    text = (
        (message_ctx.contact_phone or message_ctx.text or "").strip()
        if field_key == "phone" and profile_type == "advertiser"
        else (message_ctx.text or "").strip()
    )

    if profile_type == "advertiser":
        advertiser = await profile_service.get_advertiser_profile(user_id)
        if advertiser is None:
            await state.clear()
            msg_adv = await bot_texts_service.get(
                "msg_advertiser_profile_not_found", config.market.default_locale
            )
            await message_ctx.answer(msg_adv)
            return
        await _update_advertiser_field(
            message_ctx,
            state,
            field_key,
            text,
            user_id,
            external_id,
            advertiser,
            profile_service,
            advertiser_registration_service,
            user_role_service,
            config,
            bot_texts_service,
        )
        return

    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        await state.clear()
        msg_not_found = await bot_texts_service.get(
            "msg_profile_not_found", config.market.default_locale
        )
        await message_ctx.answer(msg_not_found)
        return

    locale = config.market.default_locale
    lat = getattr(message_ctx, "location_lat", None)
    lon = getattr(message_ctx, "location_lon", None)
    wad = getattr(message_ctx, "web_app_data", None)
    if field_key == "city" and lat is None and lon is None and wad:
        try:
            data = json.loads(wad)
            la = data.get("lat")
            lo = data.get("lon")
            if la is not None and lo is not None:
                lat, lon = float(la), float(lo)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if (
        field_key == "city"
        and lat is not None
        and lon is not None
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        result = await blogger_registration_service.resolve_city_from_location(
            lat, lon
        )
        if result is not None:
            city_name, region_name, country_name = result
            normalized = normalize_geo_token(city_name)
            if normalized:
                wkt = wkt_multipoint_from_lat_lon(lat, lon)
                reg_svc = blogger_registration_service
                updated = await reg_svc.update_blogger_profile(
                    user_id,
                    city=normalized,
                    region=region_name,
                    country=country_name or None,
                    location_geometry=wkt,
                )
                if updated is not None:
                    await state.clear()
                    msg_updated = await bot_texts_service.get(
                        "msg_profile_updated", locale
                    )
                    await message_ctx.answer(
                        msg_updated,
                        reply_markup=flow_keyboard_remove(),
                    )
                    await show_profile(
                        message=message_ctx,
                        profile_service=profile_service,
                        state=state,
                        config=config,
                        bot_texts_service=bot_texts_service,
                        messenger_client=messenger_client,
                        event_adapter=event_adapter,
                    )
                    return
        err_loc = await bot_texts_service.get("err_city_from_location", locale)
        await message_ctx.answer(err_loc, reply_markup=flow_keyboard_remove())
        return

    await _update_blogger_field(
        message_ctx,
        state,
        field_key,
        text,
        user_id,
        external_id,
        blogger,
        profile_service,
        blogger_registration_service,
        user_role_service,
        max_order_price,
        config,
        bot_texts_service,
    )
