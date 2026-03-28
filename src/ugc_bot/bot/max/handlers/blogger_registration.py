"""Blogger registration flow handlers for Max messenger."""

import logging
import re
from datetime import date
from uuid import UUID

from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
)
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import (
    UserRoleService,
    _extract_instagram_username,
)
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.blogger_registration import (
    _get_location_from_incoming,
    _handle_city_from_location,
)
from ugc_bot.bot.telegram.handlers.instagram_verification import (
    _format_verification_instruction,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_BLOGGER_AGE_0_17,
    CALLBACK_BLOGGER_AGE_18_24,
    CALLBACK_BLOGGER_AGE_25_34,
    CALLBACK_BLOGGER_AGE_35_44,
    CALLBACK_BLOGGER_AGE_45_99,
    CALLBACK_BLOGGER_AGREE,
    CALLBACK_BLOGGER_AUDIENCE_A,
    CALLBACK_BLOGGER_AUDIENCE_F,
    CALLBACK_BLOGGER_AUDIENCE_M,
    CALLBACK_BLOGGER_BARTER_N,
    CALLBACK_BLOGGER_BARTER_Y,
    CALLBACK_BLOGGER_GENDER_F,
    CALLBACK_BLOGGER_GENDER_M,
    CALLBACK_BLOGGER_RETRY_INSTAGRAM,
    CALLBACK_BLOGGER_WORK_ADS,
    CALLBACK_BLOGGER_WORK_UGC,
    CALLBACK_CREATOR_CREATE,
    CALLBACK_ROLE_CREATOR,
    blogger_after_registration_inline_keyboard,
    blogger_verification_sent_inline_keyboard,
    confirm_agreement_inline_keyboard,
    creator_filled_profile_inline_keyboard,
    creator_start_keyboard,
    flow_inline_keyboard,
    flow_inline_keyboard_location_request,
    flow_inline_keyboard_phone_request,
    flow_keyboard_remove,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    handle_role_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.telegram.validators import (
    INSTAGRAM_URL_REGEX,
    VALIDATOR_ERR_KEYS,
    normalize_instagram_url,
    validate_audience_geo,
    validate_birth_date,
    validate_city,
    validate_phone,
    validate_price,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import AudienceGender, BloggerGender, WorkFormat

router = MaxRouter()
logger = logging.getLogger(__name__)

# FSM state names for blogger registration
STATE_BLOG_INSTAGRAM = "blog_instagram"
STATE_BLOG_PHONE = "blog_phone"
STATE_BLOG_CITY = "blog_city"
STATE_BLOG_PRICE = "blog_price"
STATE_BLOG_BARTER = "blog_barter"
STATE_BLOG_GENDER = "blog_gender"
STATE_BLOG_AUDIENCE_GENDER = "blog_audience_gender"
STATE_BLOG_AUDIENCE_AGE = "blog_audience_age"
STATE_BLOG_AUDIENCE_GEO = "blog_audience_geo"
STATE_BLOG_TOPICS = "blog_topics"
STATE_BLOG_BIRTH_DATE = "blog_birth_date"
STATE_BLOG_WORK_FORMAT = "blog_work_format"
STATE_BLOG_AGREEMENTS = "blog_agreements"

# Callback → gender/age/barter/work mappings
_BLOGGER_GENDER_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_GENDER_M: "btn_gender_m",
    CALLBACK_BLOGGER_GENDER_F: "btn_gender_f",
}
_AUDIENCE_GENDER_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_AUDIENCE_F: "btn_audience_f",
    CALLBACK_BLOGGER_AUDIENCE_M: "btn_audience_m",
    CALLBACK_BLOGGER_AUDIENCE_A: "btn_audience_a",
}
_AGE_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_AGE_0_17: "btn_age_0_17",
    CALLBACK_BLOGGER_AGE_18_24: "btn_age_18_24",
    CALLBACK_BLOGGER_AGE_25_34: "btn_age_25_34",
    CALLBACK_BLOGGER_AGE_35_44: "btn_age_35_44",
    CALLBACK_BLOGGER_AGE_45_99: "btn_age_45_99",
}
_AGE_CALLBACK_TO_RANGE: dict[str, tuple[int, int]] = {
    CALLBACK_BLOGGER_AGE_0_17: (1, 17),
    CALLBACK_BLOGGER_AGE_18_24: (18, 24),
    CALLBACK_BLOGGER_AGE_25_34: (25, 34),
    CALLBACK_BLOGGER_AGE_35_44: (35, 44),
    CALLBACK_BLOGGER_AGE_45_99: (45, 99),
}
_BARTER_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_BARTER_Y: "btn_barter_yes",
    CALLBACK_BLOGGER_BARTER_N: "btn_barter_no",
}
_WORK_FORMAT_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_WORK_ADS: "btn_work_format_ads",
    CALLBACK_BLOGGER_WORK_UGC: "btn_work_format_ugc_only",
}


def _get_services(
    deps: dict,
) -> tuple[
    MessengerClient,
    StateStore,
    BotTextsService,
    str,
]:
    """Extract common services from deps."""
    messenger_client: MessengerClient = deps["messenger_client"]
    state_store: StateStore = deps["state_store"]
    bot_texts_service: BotTextsService = deps["bot_texts_service"]
    locale: str = deps.get("locale", "ru")
    return messenger_client, state_store, bot_texts_service, locale


async def _remove_inline_keyboard(
    incoming: IncomingCallback,
    messenger_client: MessengerClient,
    selected_label: str | None = None,
) -> None:
    """Remove inline keyboard; if selected_label given, append it to text."""
    if not incoming.message_id:
        return
    if selected_label and incoming.message_text:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=f"{incoming.message_text}: {selected_label}",
        )
    else:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )


async def _save_blogger_and_show_agreements(
    incoming: IncomingMessage | IncomingCallback,
    state_store: StateStore,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    config: AppConfig,
    work_format: WorkFormat,
    locale: str,
) -> None:
    """Save blogger profile and show agreements message."""
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    await state_store.update_data(work_format=work_format)

    try:
        birth_date_raw = data.get("birth_date")
        birth_date_val = (
            date.fromisoformat(birth_date_raw) if birth_date_raw else None
        )
        await blogger_registration_service.save_blogger_before_agreement(
            user_id=user_id,
            instagram_url=data["instagram_url"],
            city=data["city"],
            topics=data["topics"],
            audience_gender=data["audience_gender"],
            audience_age_min=data["audience_age_min"],
            audience_age_max=data["audience_age_max"],
            audience_geo=data["audience_geo"],
            price=data["price"],
            barter=data["barter"],
            work_format=work_format,
            blogger_gender=data["blogger_gender"],
            display_name=data.get("nickname"),
            telegram_username=None,
            birth_date=birth_date_val,
            region=data.get("region"),
            location_geometry=data.get("location_geometry"),
            country=data.get("country"),
            phone=data.get("phone"),
        )
    except Exception as exc:
        error_str = str(exc)
        is_duplicate = (
            "UniqueViolation" in error_str and "instagram_url" in error_str
        ) or "уже зарегистрирован" in error_str
        if is_duplicate:
            logger.warning(
                "Instagram URL already exists",
                extra={
                    "user_id": str(user_id),
                    "instagram_url": data.get("instagram_url"),
                },
            )
            msg_already = await bot_texts_service.get(
                "msg_instagram_already_registered", locale
            )
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=msg_already,
            )
            return
        raise

    agree_keys = [
        "btn_confirm_agreement",
        "msg_agreements_intro_creator",
        "msg_agreements_intro_default",
        "msg_label_offer",
        "msg_label_privacy",
        "msg_label_consent",
        "msg_confirm_docs_fallback",
    ]
    agree_texts = await bot_texts_service.get_many(agree_keys, locale)
    agreements_intro = agree_texts.get("msg_agreements_intro_creator", "")
    agreements_text = format_agreements_message(
        config,
        intro=agreements_intro,
        texts=agree_texts,
        country_code=data.get("user_country"),
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=agreements_text,
        parse_mode="HTML",
        keyboard=confirm_agreement_inline_keyboard(
            CALLBACK_BLOGGER_AGREE, agree_texts
        ),
    )
    await state_store.set_state(STATE_BLOG_AGREEMENTS)


# --- Role selection ---


@router.callback(lambda c: c.data == CALLBACK_ROLE_CREATOR)
async def handle_role_creator_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle creator role selection via inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(incoming, messenger_client)

    profile_service: ProfileService = deps["profile_service"]
    user_role_service: UserRoleService = deps["user_role_service"]

    texts = await bot_texts_service.get_many(
        [
            "btn_create_profile",
            "btn_edit_profile",
            "btn_my_profile",
            "btn_my_orders",
            "btn_support",
            "msg_choose_action",
        ],
        locale,
    )
    choose_action_text = texts.get("msg_choose_action", "Выберите действие:")
    intro_text = await bot_texts_service.get("msg_creator_intro", locale)

    await handle_role_choice(
        incoming,  # type: ignore[arg-type]
        messenger_client,
        user_role_service,
        state_store,
        profile_getter=profile_service.get_blogger_profile,
        choose_action_text=choose_action_text,
        intro_text=intro_text or choose_action_text,
        menu_keyboard=creator_filled_profile_inline_keyboard,
        start_keyboard=creator_start_keyboard,
        texts=texts,
    )


# --- Start blogger registration ---


@router.callback(lambda c: c.data == CALLBACK_CREATOR_CREATE)
async def handle_creator_create_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle 'Create profile' inline button to start blogger registration."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(incoming, messenger_client)

    user_role_service: UserRoleService = deps["user_role_service"]

    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_registration_blocked",
            "msg_registration_pause",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_user_not_found_start", ""),
        )
        return

    from ugc_bot.domain.enums import UserStatus

    if getattr(user, "status", None) == UserStatus.BLOCKED:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_registration_blocked", ""),
        )
        return

    user_id = getattr(user, "user_id", None)
    if not isinstance(user_id, UUID):
        return

    await state_store.update_data(
        user_id=str(user_id),
        user_country=getattr(user, "country", None),
    )

    step_instagram = await bot_texts_service.get(
        "msg_step_ask_instagram", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_instagram,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_INSTAGRAM)


# --- FSM step handlers ---


@router.message_in_state(STATE_BLOG_INSTAGRAM)
async def handle_instagram(incoming: IncomingMessage, deps: dict) -> None:
    """Store Instagram URL and ask for phone."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    blogger_registration_service: BloggerRegistrationService = deps[
        "blogger_registration_service"
    ]

    err_empty = await bot_texts_service.get("err_instagram_empty", locale)
    err_format = await bot_texts_service.get("err_instagram_format", locale)
    err_example = await bot_texts_service.get("err_instagram_example", locale)

    instagram_url = normalize_instagram_url((incoming.text or "").strip())
    if not instagram_url:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_empty,
        )
        return
    if "instagram.com/" not in instagram_url.lower():
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_format,
        )
        return
    if not INSTAGRAM_URL_REGEX.match(instagram_url):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_example,
        )
        return

    ig_username = _extract_instagram_username(instagram_url)
    existing_profile = None
    if ig_username:
        svc = blogger_registration_service
        existing_profile = await svc.get_profile_by_instagram_username(
            ig_username
        )
    if existing_profile is not None:
        instagram_verification_service: InstagramVerificationService = deps[
            "instagram_verification_service"
        ]
        config: AppConfig = deps["config"]
        verification = await instagram_verification_service.generate_code(
            existing_profile.user_id,
            link_max_id=incoming.user.external_id,
            link_max_chat_id=incoming.chat_id,
            link_username=incoming.user.username or "",
        )
        instruction_template = await bot_texts_service.get(
            "msg_instagram_verify_instruction", locale
        )
        instruction = _format_verification_instruction(
            instruction_template,
            config.instagram.admin_instagram_username,
        )
        instruction_plain = re.sub(r"<[^>]+>", "", instruction)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=instruction_plain,
        )
        admin_username = (
            config.instagram.admin_instagram_username or ""
        ).lstrip("@")
        direct_url = (
            f"https://ig.me/m/{admin_username}" if admin_username else None
        )
        texts_v = await bot_texts_service.get_many(
            ["btn_open_direct", "btn_my_profile"], locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=verification.code,
            keyboard=blogger_verification_sent_inline_keyboard(
                texts_v, direct_url=direct_url
            ),
        )
        await state_store.clear()
        return

    await state_store.update_data(instagram_url=instagram_url)
    texts = await bot_texts_service.get_many(
        ["btn_phone_request", "msg_phone_request"], locale
    )
    phone_prompt = texts.get("msg_phone_request", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=phone_prompt,
        keyboard=flow_inline_keyboard_phone_request(texts),
    )
    await state_store.set_state(STATE_BLOG_PHONE)


@router.message_in_state(STATE_BLOG_PHONE)
async def handle_phone(incoming: IncomingMessage, deps: dict) -> None:
    """Store phone and ask for city."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    phone = (incoming.contact_phone or incoming.text or "").strip()
    err = validate_phone(phone, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(phone=phone)
    city_texts = await bot_texts_service.get_many(
        ["msg_step_ask_city", "btn_location_request"], locale
    )
    step_city = city_texts.get("msg_step_ask_city", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_city,
        keyboard=flow_inline_keyboard_location_request(city_texts),
    )
    await state_store.set_state(STATE_BLOG_CITY)


@router.message_in_state(STATE_BLOG_CITY)
async def handle_city(incoming: IncomingMessage, deps: dict) -> None:
    """Store city (text or location) and ask for birth date."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    blogger_registration_service: BloggerRegistrationService = deps[
        "blogger_registration_service"
    ]

    # Handle shared location first
    location = _get_location_from_incoming(incoming)
    if location is not None:
        lat, lon = location
        await _handle_city_from_location(
            incoming,
            state_store,
            lat,
            lon,
            blogger_registration_service,
            messenger_client,
            bot_texts_service,
            locale,
        )
        return

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    city = (incoming.text or "").strip()
    err = validate_city(city, required=True, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    from ugc_bot.application.geography import normalize_geo_token

    normalized = normalize_geo_token(city)
    location_result = (
        await blogger_registration_service.resolve_city_to_location(normalized)
    )

    if location_result is None:
        err_not_found = await bot_texts_service.get(
            "err_city_not_found_use_map", locale
        )
        loc_texts = await bot_texts_service.get_many(
            ["btn_location_request"], locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_not_found,
            keyboard=flow_inline_keyboard_location_request(loc_texts),
        )
        return

    location_geometry, region_geo, country_geo = location_result
    country = (country_geo or "").strip()
    region = region_geo or ""
    await state_store.update_data(
        city=normalized,
        region=region,
        location_geometry=location_geometry,
        country=country,
    )

    step_birth_date = await bot_texts_service.get(
        "msg_step_ask_birth_date", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_birth_date,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_BIRTH_DATE)


@router.message_in_state(STATE_BLOG_BIRTH_DATE)
async def handle_birth_date(incoming: IncomingMessage, deps: dict) -> None:
    """Store birth date and ask for blogger gender."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    text = (incoming.text or "").strip()
    parsed_date, err = validate_birth_date(text, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    assert parsed_date is not None

    await state_store.update_data(birth_date=parsed_date.isoformat())

    step_gender = await bot_texts_service.get("msg_step_ask_gender", locale)
    gender_texts = await bot_texts_service.get_many(
        ["btn_gender_m", "btn_gender_f"], locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_gender,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=gender_texts["btn_gender_m"],
                        callback_data=CALLBACK_BLOGGER_GENDER_M,
                    ),
                    Button(
                        text=gender_texts["btn_gender_f"],
                        callback_data=CALLBACK_BLOGGER_GENDER_F,
                    ),
                ],
            ],
        ),
    )
    await state_store.set_state(STATE_BLOG_GENDER)


@router.callback_in_state(
    STATE_BLOG_GENDER,
    lambda c: c.data in (CALLBACK_BLOGGER_GENDER_M, CALLBACK_BLOGGER_GENDER_F),
)
async def handle_blogger_gender_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Store blogger gender from inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    data = incoming.data or ""
    if data == CALLBACK_BLOGGER_GENDER_M:
        blogger_gender: BloggerGender | None = BloggerGender.MALE
    elif data == CALLBACK_BLOGGER_GENDER_F:
        blogger_gender = BloggerGender.FEMALE
    else:
        blogger_gender = None

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    if blogger_gender is None:
        await _remove_inline_keyboard(incoming, messenger_client)
        return

    btn_key = _BLOGGER_GENDER_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    await _remove_inline_keyboard(
        incoming, messenger_client, selected_label=label
    )

    step_topics = await bot_texts_service.get("msg_step_ask_topics", locale)
    await state_store.update_data(blogger_gender=blogger_gender)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_topics,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_TOPICS)


@router.message_in_state(STATE_BLOG_TOPICS)
async def handle_topics(incoming: IncomingMessage, deps: dict) -> None:
    """Store blogger topics and ask for audience gender."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    raw = (incoming.text or "").strip()
    topics = [
        topic.strip().lower() for topic in raw.split(",") if topic.strip()
    ]
    err = validate_topics(topics, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(topics={"selected": topics})

    step_audience = await bot_texts_service.get(
        "msg_step_ask_audience_gender", locale
    )
    aud_texts = await bot_texts_service.get_many(
        ["btn_audience_f", "btn_audience_m", "btn_audience_a"], locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_audience,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=aud_texts["btn_audience_f"],
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_F,
                    )
                ],
                [
                    Button(
                        text=aud_texts["btn_audience_m"],
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_M,
                    )
                ],
                [
                    Button(
                        text=aud_texts["btn_audience_a"],
                        callback_data=CALLBACK_BLOGGER_AUDIENCE_A,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(STATE_BLOG_AUDIENCE_GENDER)


@router.callback_in_state(
    STATE_BLOG_AUDIENCE_GENDER,
    lambda c: (
        c.data
        in (
            CALLBACK_BLOGGER_AUDIENCE_F,
            CALLBACK_BLOGGER_AUDIENCE_M,
            CALLBACK_BLOGGER_AUDIENCE_A,
        )
    ),
)
async def handle_audience_gender_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Store audience gender from inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    data = incoming.data or ""
    if data == CALLBACK_BLOGGER_AUDIENCE_F:
        audience_gender: AudienceGender | None = AudienceGender.FEMALE
    elif data == CALLBACK_BLOGGER_AUDIENCE_M:
        audience_gender = AudienceGender.MALE
    elif data == CALLBACK_BLOGGER_AUDIENCE_A:
        audience_gender = AudienceGender.ALL
    else:
        audience_gender = None

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    if audience_gender is None:
        await _remove_inline_keyboard(incoming, messenger_client)
        return

    btn_key = _AUDIENCE_GENDER_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    await _remove_inline_keyboard(
        incoming, messenger_client, selected_label=label
    )

    await state_store.update_data(audience_gender=audience_gender)

    step_age = await bot_texts_service.get("msg_step_ask_audience_age", locale)
    age_texts = await bot_texts_service.get_many(
        [
            "btn_age_0_17",
            "btn_age_18_24",
            "btn_age_25_34",
            "btn_age_35_44",
            "btn_age_45_99",
        ],
        locale,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_age,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=age_texts["btn_age_0_17"],
                        callback_data=CALLBACK_BLOGGER_AGE_0_17,
                    )
                ],
                [
                    Button(
                        text=age_texts["btn_age_18_24"],
                        callback_data=CALLBACK_BLOGGER_AGE_18_24,
                    )
                ],
                [
                    Button(
                        text=age_texts["btn_age_25_34"],
                        callback_data=CALLBACK_BLOGGER_AGE_25_34,
                    )
                ],
                [
                    Button(
                        text=age_texts["btn_age_35_44"],
                        callback_data=CALLBACK_BLOGGER_AGE_35_44,
                    )
                ],
                [
                    Button(
                        text=age_texts["btn_age_45_99"],
                        callback_data=CALLBACK_BLOGGER_AGE_45_99,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(STATE_BLOG_AUDIENCE_AGE)


@router.callback_in_state(
    STATE_BLOG_AUDIENCE_AGE,
    lambda c: (c.data or "") in _AGE_CALLBACK_TO_RANGE,
)
async def handle_audience_age_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Store audience age from inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    data = incoming.data or ""
    if data not in _AGE_CALLBACK_TO_RANGE:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard(incoming, messenger_client)
        return

    min_age, max_age = _AGE_CALLBACK_TO_RANGE[data]
    btn_key = _AGE_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(
        incoming, messenger_client, selected_label=label
    )

    await state_store.update_data(
        audience_age_min=min_age, audience_age_max=max_age
    )
    step_geo = await bot_texts_service.get("msg_step_ask_audience_geo", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_geo,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_AUDIENCE_GEO)


@router.message_in_state(STATE_BLOG_AUDIENCE_GEO)
async def handle_audience_geo(incoming: IncomingMessage, deps: dict) -> None:
    """Store audience geography (up to 3 cities) and ask for price."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    err_geo = await bot_texts_service.get("err_geo_max_cities", locale)
    currency_symbol: str = deps.get("currency_symbol", "")
    step_price = (
        await bot_texts_service.get("msg_step_ask_price", locale)
    ).format(currency=currency_symbol)

    geo = (incoming.text or "").strip()
    err = validate_audience_geo(geo, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    cities = [c.strip() for c in geo.split(",") if c.strip()]
    if len(cities) > 3:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_geo,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(audience_geo=geo)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_price,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_PRICE)


@router.message_in_state(STATE_BLOG_PRICE)
async def handle_price(incoming: IncomingMessage, deps: dict) -> None:
    """Store price and ask for barter preference."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    max_order_price: float = deps.get("max_order_price", 999999.0)
    currency_symbol: str = deps.get("currency_symbol", "")
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    err_price = await bot_texts_service.get("err_price_number", locale)
    step_barter = await bot_texts_service.get("msg_step_ask_barter", locale)
    barter_texts = await bot_texts_service.get_many(
        ["btn_barter_yes", "btn_barter_no"], locale
    )

    raw = (incoming.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_price,
        )
        return

    err = validate_price(
        price, max_order_price, currency_symbol, texts=validator_texts
    )
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(price=price)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_barter,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=barter_texts["btn_barter_yes"],
                        callback_data=CALLBACK_BLOGGER_BARTER_Y,
                    )
                ],
                [
                    Button(
                        text=barter_texts["btn_barter_no"],
                        callback_data=CALLBACK_BLOGGER_BARTER_N,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(STATE_BLOG_BARTER)


@router.callback_in_state(
    STATE_BLOG_BARTER,
    lambda c: c.data in (CALLBACK_BLOGGER_BARTER_Y, CALLBACK_BLOGGER_BARTER_N),
)
async def handle_barter_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Store barter preference from inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    data = incoming.data or ""
    barter = data == CALLBACK_BLOGGER_BARTER_Y

    btn_key = _BARTER_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(
        incoming, messenger_client, selected_label=label
    )

    await state_store.update_data(barter=barter)

    step_work = await bot_texts_service.get("msg_step_ask_work_format", locale)
    work_texts = await bot_texts_service.get_many(
        ["btn_work_format_ads", "btn_work_format_ugc_only"], locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_work,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=work_texts["btn_work_format_ads"],
                        callback_data=CALLBACK_BLOGGER_WORK_ADS,
                    )
                ],
                [
                    Button(
                        text=work_texts["btn_work_format_ugc_only"],
                        callback_data=CALLBACK_BLOGGER_WORK_UGC,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(STATE_BLOG_WORK_FORMAT)


@router.callback_in_state(
    STATE_BLOG_WORK_FORMAT,
    lambda c: c.data in (CALLBACK_BLOGGER_WORK_ADS, CALLBACK_BLOGGER_WORK_UGC),
)
async def handle_work_format_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Store work format from inline button, save profile, show agreements."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    blogger_registration_service: BloggerRegistrationService = deps[
        "blogger_registration_service"
    ]
    config: AppConfig = deps["config"]

    data = incoming.data or ""
    if data == CALLBACK_BLOGGER_WORK_ADS:
        work_format: WorkFormat | None = WorkFormat.ADS_IN_ACCOUNT
    elif data == CALLBACK_BLOGGER_WORK_UGC:
        work_format = WorkFormat.UGC_ONLY
    else:
        work_format = None

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    if work_format is None:
        await _remove_inline_keyboard(incoming, messenger_client)
        return

    btn_key = _WORK_FORMAT_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    await _remove_inline_keyboard(
        incoming, messenger_client, selected_label=label
    )

    await _save_blogger_and_show_agreements(
        incoming,
        state_store,
        messenger_client,
        bot_texts_service,
        blogger_registration_service,
        config,
        work_format,
        locale,
    )


@router.callback_in_state(
    STATE_BLOG_AGREEMENTS, lambda c: c.data == CALLBACK_BLOGGER_AGREE
)
async def handle_agreements_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Finalize blogger registration after user confirms agreement (inline)."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    blogger_registration_service: BloggerRegistrationService = deps[
        "blogger_registration_service"
    ]

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(incoming, messenger_client)

    if user_id is None:
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    await blogger_registration_service.confirm_blogger_agreement(
        user_id=user_id,
        telegram_username=None,
    )
    await state_store.clear()

    msg_profile_created = await bot_texts_service.get(
        "msg_profile_created", locale
    )
    after_texts = await bot_texts_service.get_many(
        ["btn_confirm_instagram", "btn_my_profile"],
        locale,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_profile_created,
        keyboard=blogger_after_registration_inline_keyboard(after_texts),
    )


@router.callback(
    lambda c: c.data == CALLBACK_BLOGGER_RETRY_INSTAGRAM,
)
async def handle_retry_instagram_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Return user to Instagram URL input step."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    step_instagram = await bot_texts_service.get(
        "msg_step_ask_instagram", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_instagram,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_BLOG_INSTAGRAM)
