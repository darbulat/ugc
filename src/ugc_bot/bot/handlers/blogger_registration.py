"""Blogger registration flow handlers."""

import json
import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.geography import (
    get_regions_for_city,
    normalize_geo_token,
)

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.messenger.dto import Button, IncomingCallback
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import CountryRepository
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.geocoder import wkt_multipoint_from_lat_lon
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
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
    CALLBACK_BLOGGER_REGION_PREFIX,
    CALLBACK_BLOGGER_WORK_ADS,
    CALLBACK_BLOGGER_WORK_UGC,
    CALLBACK_CREATOR_CREATE,
    CALLBACK_ROLE_CREATOR,
    blogger_after_registration_inline_keyboard,
    build_support_telegram_url,
    confirm_agreement_inline_keyboard,
    creator_filled_profile_inline_keyboard,
    creator_start_keyboard,
    flow_inline_keyboard,
    flow_keyboard_city_request,
    flow_keyboard_phone_request,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    handle_role_choice,
    parse_user_id_from_state,
    resolve_currency_symbol,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
    INSTAGRAM_URL_REGEX,
    VALIDATOR_ERR_KEYS,
    normalize_instagram_url,
    validate_audience_geo,
    validate_birth_date,
    validate_city,
    validate_nickname,
    validate_phone,
    validate_price,
    validate_topics,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    WorkFormat,
)
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()
logger = logging.getLogger(__name__)

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

_BARTER_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_BARTER_Y: "btn_barter_yes",
    CALLBACK_BLOGGER_BARTER_N: "btn_barter_no",
}

_WORK_FORMAT_CALLBACK_TO_BTN = {
    CALLBACK_BLOGGER_WORK_ADS: "btn_work_format_ads",
    CALLBACK_BLOGGER_WORK_UGC: "btn_work_format_ugc_only",
}


async def _remove_inline_keyboard_from_callback(
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


class BloggerRegistrationStates(StatesGroup):
    """States for blogger registration."""

    name = State()
    phone = State()
    instagram = State()
    city = State()
    birth_date = State()
    blogger_gender = State()
    topics = State()
    audience_gender = State()
    audience_age = State()
    audience_geo = State()
    price = State()
    barter = State()
    work_format = State()
    agreements = State()


BLOGGER_FLOW_TYPE = "blogger_registration"


async def _choose_creator_role_impl(
    incoming,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient,
    locale: str,
    support_url: str | None = None,
) -> None:
    """Shared logic for creator role: show menu or registration prompt."""
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
    choose_action_text = await bot_texts_service.get(
        "msg_choose_action", locale
    )
    intro_text = await bot_texts_service.get("msg_creator_intro", locale)
    menu_kb = (
        (
            lambda t: creator_filled_profile_inline_keyboard(
                t, support_url=support_url
            )
        )
        if support_url is not None
        else creator_filled_profile_inline_keyboard
    )
    await handle_role_choice(
        incoming,
        messenger_client,
        user_role_service,
        AiogramStateStore(state),
        profile_getter=profile_service.get_blogger_profile,
        choose_action_text=choose_action_text,
        intro_text=intro_text,
        menu_keyboard=menu_kb,
        start_keyboard=creator_start_keyboard,
        texts=texts,
    )


@router.callback_query(lambda c: c.data == CALLBACK_ROLE_CREATOR)
async def choose_creator_role_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle creator role via inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    locale = user_locale
    support_url = build_support_telegram_url(
        config.market.support_contact or ""
    )
    await _choose_creator_role_impl(
        incoming,
        state,
        user_role_service,
        profile_service,
        bot_texts_service,
        messenger_client,
        locale,
        support_url=support_url,
    )


@router.message(Command("creator"))
@router.message(TextEqualsKey("btn_creator"))
async def choose_creator_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle creator role (message): show menu or registration prompt."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    support_url = build_support_telegram_url(
        config.market.support_contact or ""
    )
    await _choose_creator_role_impl(
        incoming,
        state,
        user_role_service,
        profile_service,
        bot_texts_service,
        messenger_client,
        locale,
        support_url=support_url,
    )


async def _start_registration_flow_impl(
    chat_id: str,
    state_store: AiogramStateStore,
    user: object,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    user_locale: str = "ru",
) -> None:
    """Start blogger registration: first step (name)."""
    locale = user_locale
    step_name = await bot_texts_service.get("msg_step_ask_name", locale)
    user_id = getattr(user, "user_id", None)
    external_id = (
        getattr(user, "telegram_id", None)
        or getattr(user, "max_id", None)
    )
    await state_store.update_data(
        user_id=user_id,
        external_id=external_id,
        user_country=getattr(user, "country", None),
    )
    await messenger_client.send_text(
        chat_id=chat_id,
        text=step_name,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.name.state)


async def _start_registration_flow(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration: first step (name)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_registration_blocked",
            "msg_registration_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found_start", ""),
        blocked_msg=allow_msgs.get("msg_registration_blocked", ""),
        pause_msg=allow_msgs.get("msg_registration_pause", ""),
    )
    if user is None:
        return
    await _start_registration_flow_impl(
        incoming.chat_id,
        state_store,
        user,
        messenger_client,
        bot_texts_service,
        config,
        user_locale=locale,
    )


@router.message(TextEqualsKey("btn_create_profile"))
async def start_registration_button(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration via message (e.g. tests or legacy reply)."""
    await _start_registration_flow(
        message,
        state,
        user_role_service,
        bot_texts_service,
        config,
        user_locale=user_locale,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )


@router.callback_query(lambda c: c.data == CALLBACK_CREATOR_CREATE)
async def start_registration_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start blogger registration flow via Inline Create profile button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_registration_blocked",
            "msg_registration_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found_start", ""),
        blocked_msg=allow_msgs.get("msg_registration_blocked", ""),
        pause_msg=allow_msgs.get("msg_registration_pause", ""),
    )
    if user is None:
        return
    state_store = AiogramStateStore(state)
    await _start_registration_flow_impl(
        incoming.chat_id,
        state_store,
        user,
        messenger_client,
        bot_texts_service,
        config,
        user_locale=locale,
    )


@router.message(BloggerRegistrationStates.name)
async def handle_name(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store nickname."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    nickname = (incoming.text or "").strip()
    err = validate_nickname(nickname, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(nickname=nickname)
    texts = await bot_texts_service.get_many(
        ["btn_phone_request", "msg_phone_request"], locale
    )
    phone_prompt = texts.get("msg_phone_request", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=phone_prompt,
        keyboard=flow_keyboard_phone_request(texts),
    )
    await state_store.set_state(BloggerRegistrationStates.phone.state)


@router.message(BloggerRegistrationStates.phone)
async def handle_phone(
    message: Message,
    state: FSMContext,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store phone and ask for Instagram."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
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
    step_instagram = await bot_texts_service.get(
        "msg_step_ask_instagram", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_instagram,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.instagram.state)


@router.message(BloggerRegistrationStates.instagram)
async def handle_instagram(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store Instagram URL."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    err_empty = await bot_texts_service.get("err_instagram_empty", locale)
    err_format = await bot_texts_service.get("err_instagram_format", locale)
    err_example = await bot_texts_service.get("err_instagram_example", locale)
    msg_already = await bot_texts_service.get(
        "msg_instagram_already_registered", locale
    )
    step_city = await bot_texts_service.get("msg_step_ask_city", locale)
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

    # Check if Instagram URL is already taken
    existing_profile = (
        await blogger_registration_service.get_profile_by_instagram_url(
            instagram_url
        )
    )
    if existing_profile is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_already,
        )
        return

    await state_store.update_data(instagram_url=instagram_url)
    city_btn_texts = await bot_texts_service.get_many(
        ["btn_location_request", "btn_location_map"], locale
    )
    miniapp_url = None
    base = getattr(config.webhook, "webhook_base_url", None) or ""
    if base:
        miniapp_url = (
            base.rstrip("/") + f"/miniapp/location_picker.html?locale={locale}"
        )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_city,
        keyboard=flow_keyboard_city_request(
            city_btn_texts, miniapp_location_url=miniapp_url
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.city.state)


def _get_location_from_incoming(incoming) -> tuple[float, float] | None:
    """(lat, lon) from message location or web_app_data, or None if invalid."""
    location_lat = getattr(incoming, "location_lat", None)
    location_lon = getattr(incoming, "location_lon", None)
    if location_lat is None and location_lon is None:
        wad = getattr(incoming, "web_app_data", None)
        if wad:
            try:
                data = json.loads(wad)
                lat = data.get("lat")
                lon = data.get("lon")
                if lat is not None and lon is not None:
                    location_lat = float(lat)
                    location_lon = float(lon)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    if (
        location_lat is not None
        and location_lon is not None
        and -90 <= location_lat <= 90
        and -180 <= location_lon <= 180
    ):
        return (location_lat, location_lon)
    return None


async def _handle_city_from_location(
    incoming,
    state_store,
    location_lat: float,
    location_lon: float,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    locale: str,
) -> bool:
    """Process city from location. True if handled (success or error sent)."""
    result = await blogger_registration_service.resolve_city_from_location(
        location_lat, location_lon
    )
    if result is None:
        err_loc = await bot_texts_service.get("err_city_from_location", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_loc,
            keyboard=flow_keyboard_remove(),
        )
        return True
    city_from_geo, region_from_geo, country_from_geo = result
    normalized = normalize_geo_token(city_from_geo)
    if not normalized:
        err_loc = await bot_texts_service.get("err_city_from_location", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_loc,
            keyboard=flow_keyboard_remove(),
        )
        return True
    location_geometry = wkt_multipoint_from_lat_lon(location_lat, location_lon)
    step_birth_date = await bot_texts_service.get(
        "msg_step_ask_birth_date", locale
    )
    state_data = {
        "city": normalized,
        "region": region_from_geo or "",
        "country": (country_from_geo or "").strip(),
        "location_geometry": location_geometry,
    }
    await state_store.update_data(**state_data)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_birth_date,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.birth_date.state)
    return True


async def _city_step_keyboard_async(
    bot_texts_service: BotTextsService,
    config: AppConfig,
    locale: str,
):
    """Build city step keyboard (location + picker) for error replies."""
    city_btn_texts = await bot_texts_service.get_many(
        ["btn_location_request", "btn_location_map"], locale
    )
    miniapp_url = None
    base = getattr(config.webhook, "webhook_base_url", None) or ""
    if base:
        miniapp_url = (
            base.rstrip("/") + f"/miniapp/location_picker.html?locale={locale}"
        )
    return flow_keyboard_city_request(
        city_btn_texts, miniapp_location_url=miniapp_url
    )


async def _handle_city_from_text(
    incoming,
    state_store,
    validator_texts: dict,
    blogger_registration_service: BloggerRegistrationService,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    locale: str,
) -> None:
    """Process city from text. Validate via geocoder; on success store city and
    location_geometry, then advance to region/birth_date.
    """
    city = (incoming.text or "").strip()
    err = validate_city(city, required=True, texts=validator_texts)
    if err is not None:
        keyboard = await _city_step_keyboard_async(
            bot_texts_service, config, locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=keyboard,
        )
        return
    normalized = normalize_geo_token(city)
    location_result = (
        await blogger_registration_service.resolve_city_to_location(normalized)
    )
    if location_result is None:
        err_not_found = await bot_texts_service.get(
            "err_city_not_found_use_map", locale
        )
        keyboard = await _city_step_keyboard_async(
            bot_texts_service, config, locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_not_found,
            keyboard=keyboard,
        )
        return
    location_geometry, region_geo, country_geo = location_result
    country = (country_geo or "").strip()
    region = region_geo or ""
    step_birth_date = await bot_texts_service.get(
        "msg_step_ask_birth_date", locale
    )
    await state_store.update_data(
        city=normalized,
        region=region,
        location_geometry=location_geometry,
        country=country,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_birth_date,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.birth_date.state)


@router.message(BloggerRegistrationStates.city)
async def handle_city(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store creator city (text input or shared location)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )

    location = _get_location_from_incoming(incoming)
    if location is not None:
        await _handle_city_from_location(
            incoming,
            state_store,
            location[0],
            location[1],
            blogger_registration_service,
            messenger_client,
            bot_texts_service,
            locale,
        )
        return

    await _handle_city_from_text(
        incoming,
        state_store,
        validator_texts,
        blogger_registration_service,
        messenger_client,
        bot_texts_service,
        config,
        locale,
    )


@router.callback_query(
    lambda c: c.data and c.data.startswith(CALLBACK_BLOGGER_REGION_PREFIX),
    StateFilter(BloggerRegistrationStates.city),
)
async def handle_city_region_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store selected region for city (when city is in multiple regions)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    data = await state_store.get_data()
    city = data.get("city")
    if not city:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return
    region = (callback.data or "").removeprefix(CALLBACK_BLOGGER_REGION_PREFIX)
    if region not in get_regions_for_city(city):
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        return
    # Unreachable: no hardcoded regions (get_regions_for_city always []).
    locale = user_locale  # pragma: no cover
    step_birth_date = await bot_texts_service.get(  # pragma: no cover
        "msg_step_ask_birth_date", locale
    )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id
    )  # pragma: no cover
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client
    )  # pragma: no cover
    await state_store.update_data(region=region)  # pragma: no cover
    await messenger_client.send_text(  # pragma: no cover
        chat_id=incoming.chat_id,
        text=step_birth_date,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(
        BloggerRegistrationStates.birth_date.state
    )  # pragma: no cover


@router.message(BloggerRegistrationStates.birth_date)
async def handle_birth_date(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store creator birth date and ask for gender."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
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
    step_gender = await bot_texts_service.get("msg_step_ask_gender", locale)
    gender_texts = await bot_texts_service.get_many(
        ["btn_gender_m", "btn_gender_f"], locale
    )
    await state_store.update_data(birth_date=parsed_date.isoformat())
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
    await state_store.set_state(BloggerRegistrationStates.blogger_gender.state)


def _blogger_gender_from_callback(data: str) -> BloggerGender | None:
    """Map callback_data to BloggerGender."""
    if data == CALLBACK_BLOGGER_GENDER_M:
        return BloggerGender.MALE
    if data == CALLBACK_BLOGGER_GENDER_F:
        return BloggerGender.FEMALE
    return None


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_GENDER_M, CALLBACK_BLOGGER_GENDER_F)
)
async def handle_blogger_gender_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger gender from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.blogger_gender.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    blogger_gender = _blogger_gender_from_callback(incoming.data or "")
    if blogger_gender is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    locale = user_locale
    btn_key = _BLOGGER_GENDER_CALLBACK_TO_BTN.get(incoming.data or "")
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    step_topics = await bot_texts_service.get("msg_step_ask_topics", locale)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client, selected_label=label
    )
    await state_store.update_data(blogger_gender=blogger_gender)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_topics,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.topics.state)


@router.message(BloggerRegistrationStates.blogger_gender)
async def handle_blogger_gender(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger gender from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    btn_m = (await bot_texts_service.get("btn_gender_m", locale)).strip()
    btn_f = (await bot_texts_service.get("btn_gender_f", locale)).strip()
    err_choose = await bot_texts_service.get("err_gender_choose", locale)
    step_topics = await bot_texts_service.get("msg_step_ask_topics", locale)
    text = (incoming.text or "").strip()
    blogger_gender = None
    if text == btn_m:
        blogger_gender = BloggerGender.MALE
    elif text == btn_f:
        blogger_gender = BloggerGender.FEMALE
    if blogger_gender is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_choose,
        )
        return
    await state_store.update_data(blogger_gender=blogger_gender)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_topics,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.topics.state)


@router.message(BloggerRegistrationStates.topics)
async def handle_topics(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store blogger topics."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
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
    await state_store.set_state(BloggerRegistrationStates.audience_gender.state)


def _audience_gender_from_callback(data: str) -> AudienceGender | None:
    """Map callback_data to AudienceGender."""
    if data == CALLBACK_BLOGGER_AUDIENCE_F:
        return AudienceGender.FEMALE
    if data == CALLBACK_BLOGGER_AUDIENCE_M:
        return AudienceGender.MALE
    if data == CALLBACK_BLOGGER_AUDIENCE_A:
        return AudienceGender.ALL
    return None


@router.callback_query(
    lambda c: (
        c.data
        in (
            CALLBACK_BLOGGER_AUDIENCE_F,
            CALLBACK_BLOGGER_AUDIENCE_M,
            CALLBACK_BLOGGER_AUDIENCE_A,
        )
    )
)
async def handle_audience_gender_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience gender from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.audience_gender.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    audience_gender = _audience_gender_from_callback(incoming.data or "")
    if audience_gender is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    locale = user_locale
    btn_key = _AUDIENCE_GENDER_CALLBACK_TO_BTN.get(incoming.data or "")
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
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
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client, selected_label=label
    )
    await state_store.update_data(audience_gender=audience_gender)
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
    await state_store.set_state(BloggerRegistrationStates.audience_age.state)


@router.message(BloggerRegistrationStates.audience_gender)
async def handle_gender(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience gender from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    aud_texts = await bot_texts_service.get_many(
        ["btn_audience_f", "btn_audience_m", "btn_audience_a"], locale
    )
    gender_map = {
        aud_texts["btn_audience_f"].strip().lower(): AudienceGender.FEMALE,
        aud_texts["btn_audience_m"].strip().lower(): AudienceGender.MALE,
        aud_texts["btn_audience_a"].strip().lower(): AudienceGender.ALL,
    }
    gender_text = (incoming.text or "").strip().lower()
    if gender_text not in gender_map:
        err_choose = await bot_texts_service.get("err_audience_choose", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_choose,
        )
        return
    await state_store.update_data(audience_gender=gender_map[gender_text])
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
    await state_store.set_state(BloggerRegistrationStates.audience_age.state)


_AGE_CALLBACK_TO_RANGE: dict[str, tuple[int, int]] = {
    CALLBACK_BLOGGER_AGE_0_17: (1, 17),
    CALLBACK_BLOGGER_AGE_18_24: (18, 24),
    CALLBACK_BLOGGER_AGE_25_34: (25, 34),
    CALLBACK_BLOGGER_AGE_35_44: (35, 44),
    CALLBACK_BLOGGER_AGE_45_99: (45, 99),
}


@router.message(BloggerRegistrationStates.audience_age)
async def handle_age(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience age from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
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
    age_text_to_range = {
        age_texts["btn_age_0_17"].strip(): (1, 17),
        age_texts["btn_age_18_24"].strip(): (18, 24),
        age_texts["btn_age_25_34"].strip(): (25, 34),
        age_texts["btn_age_35_44"].strip(): (35, 44),
        age_texts["btn_age_45_99"].strip(): (45, 99),
    }
    raw = (incoming.text or "").strip()
    if raw not in age_text_to_range:
        err_choose = await bot_texts_service.get("err_age_choose", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_choose,
        )
        return
    min_age, max_age = age_text_to_range[raw]
    await state_store.update_data(
        audience_age_min=min_age, audience_age_max=max_age
    )
    step_geo = await bot_texts_service.get("msg_step_ask_audience_geo", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_geo,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_geo.state)


@router.callback_query(
    lambda c: c.data in _AGE_CALLBACK_TO_RANGE,
)
async def handle_audience_age_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience age from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.audience_age.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    data = incoming.data or ""
    if data not in _AGE_CALLBACK_TO_RANGE:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    min_age, max_age = _AGE_CALLBACK_TO_RANGE[data]
    locale = user_locale
    btn_key = _AGE_CALLBACK_TO_BTN.get(data)
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    step_geo = await bot_texts_service.get("msg_step_ask_audience_geo", locale)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client, selected_label=label
    )
    await state_store.update_data(
        audience_age_min=min_age, audience_age_max=max_age
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_geo,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(BloggerRegistrationStates.audience_geo.state)


@router.message(BloggerRegistrationStates.audience_geo)
async def handle_geo(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    currency_symbol: str = "",
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store audience geography (up to 3 cities)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    err_geo = await bot_texts_service.get("err_geo_max_cities", locale)
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
    await state_store.set_state(BloggerRegistrationStates.price.state)


@router.message(BloggerRegistrationStates.price)
async def handle_price(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    max_order_price: float,
    currency_symbol: str,
    user_locale: str = "ru",
    user_role_service: UserRoleService | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
) -> None:
    """Store price."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    if incoming.user and user_role_service:
        user_obj = await user_role_service.get_user(
            external_id=incoming.user.external_id,
            messenger_type=MessengerType.TELEGRAM,
        )
        currency_symbol = await resolve_currency_symbol(
            user_obj, country_repo, currency_symbol
        )
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
    await state_store.set_state(BloggerRegistrationStates.barter.state)


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_BARTER_Y, CALLBACK_BLOGGER_BARTER_N),
)
async def handle_barter_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store barter preference from inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.barter.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    barter = incoming.data == CALLBACK_BLOGGER_BARTER_Y
    locale = user_locale
    btn_key = _BARTER_CALLBACK_TO_BTN.get(incoming.data or "")
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    step_work = await bot_texts_service.get("msg_step_ask_work_format", locale)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client, selected_label=label
    )
    await state_store.update_data(barter=barter)
    texts = await bot_texts_service.get_many(
        ["btn_work_format_ads", "btn_work_format_ugc_only"],
        locale,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_work,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=texts["btn_work_format_ads"],
                        callback_data=CALLBACK_BLOGGER_WORK_ADS,
                    )
                ],
                [
                    Button(
                        text=texts["btn_work_format_ugc_only"],
                        callback_data=CALLBACK_BLOGGER_WORK_UGC,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.work_format.state)


@router.message(BloggerRegistrationStates.barter)
async def handle_barter(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store barter preference from message text (e.g. tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    btn_yes = (await bot_texts_service.get("btn_barter_yes", locale)).strip()
    btn_no = (await bot_texts_service.get("btn_barter_no", locale)).strip()
    text = (incoming.text or "").strip()
    if text == btn_yes:
        barter = True
    elif text == btn_no:
        barter = False
    else:
        err_barter = await bot_texts_service.get("err_barter_choose", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err_barter,
        )
        return
    await state_store.update_data(barter=barter)
    locale = user_locale
    step_work = await bot_texts_service.get("msg_step_ask_work_format", locale)
    texts = await bot_texts_service.get_many(
        ["btn_work_format_ads", "btn_work_format_ugc_only"],
        locale,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=step_work,
        keyboard=flow_inline_keyboard(
            rows=[
                [
                    Button(
                        text=texts["btn_work_format_ads"],
                        callback_data=CALLBACK_BLOGGER_WORK_ADS,
                    )
                ],
                [
                    Button(
                        text=texts["btn_work_format_ugc_only"],
                        callback_data=CALLBACK_BLOGGER_WORK_UGC,
                    )
                ],
            ],
        ),
    )
    await state_store.set_state(BloggerRegistrationStates.work_format.state)


def _work_format_from_callback(data: str) -> WorkFormat | None:
    """Map callback_data to WorkFormat."""
    if data == CALLBACK_BLOGGER_WORK_ADS:
        return WorkFormat.ADS_IN_ACCOUNT
    if data == CALLBACK_BLOGGER_WORK_UGC:
        return WorkFormat.UGC_ONLY
    return None


@router.callback_query(
    lambda c: c.data in (CALLBACK_BLOGGER_WORK_ADS, CALLBACK_BLOGGER_WORK_UGC),
)
async def handle_work_format_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store work format from inline button, save profile, show agreements."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.work_format.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    work_format = _work_format_from_callback(incoming.data or "")
    if work_format is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return
    locale = user_locale
    btn_key = _WORK_FORMAT_CALLBACK_TO_BTN.get(incoming.data or "")
    label = await bot_texts_service.get(btn_key, locale) if btn_key else None
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(
        incoming, messenger_client, selected_label=label
    )
    await state_store.update_data(work_format=work_format)
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        msg_expired = await bot_texts_service.get(
            "msg_session_expired", user_locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    try:
        telegram_username = getattr(incoming.user, "username", None)
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
            telegram_username=telegram_username,
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
                "msg_instagram_already_registered",
                user_locale,
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
    agree_texts = await bot_texts_service.get_many(agree_keys, user_locale)
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
    await state_store.set_state(BloggerRegistrationStates.agreements.state)


@router.message(BloggerRegistrationStates.work_format)
async def handle_work_format(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store work format from message, save profile, show agreements (tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    btn_ads = (
        await bot_texts_service.get("btn_work_format_ads", locale)
    ).strip()
    btn_ugc = (
        await bot_texts_service.get("btn_work_format_ugc_only", locale)
    ).strip()
    text = (incoming.text or "").strip()
    if text == btn_ads:
        work_format = WorkFormat.ADS_IN_ACCOUNT
    elif text == btn_ugc:
        work_format = WorkFormat.UGC_ONLY
    else:
        msg_choose = await bot_texts_service.get(
            "msg_work_format_choose", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_choose,
        )
        return
    await state_store.update_data(work_format=work_format)
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
    try:
        telegram_username = getattr(incoming.user, "username", None)
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
            telegram_username=telegram_username,
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
    await state_store.set_state(BloggerRegistrationStates.agreements.state)


@router.callback_query(lambda c: c.data == CALLBACK_BLOGGER_AGREE)
async def handle_agreements_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Finalize blogger registration after user confirms agreement (inline)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != BloggerRegistrationStates.agreements.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        locale = user_locale
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    try:
        telegram_username = getattr(incoming.user, "username", None)
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=telegram_username,
        )
    except Exception:
        raise

    await state_store.clear()
    locale = user_locale
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


@router.message(BloggerRegistrationStates.agreements)
async def handle_agreements(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    blogger_registration_service: BloggerRegistrationService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Finalize blogger registration after message Confirm agreement (tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    confirm_btn = (
        await bot_texts_service.get("btn_confirm_agreement", user_locale)
    ).strip()
    locale = user_locale
    if (incoming.text or "").strip() != confirm_btn:
        msg_aborted = await bot_texts_service.get(
            "msg_registration_aborted", locale
        )
        await state_store.clear()
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_aborted,
            keyboard=flow_keyboard_remove(),
        )
        return
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
    try:
        telegram_username = getattr(incoming.user, "username", None)
        await blogger_registration_service.confirm_blogger_agreement(
            user_id=user_id,
            telegram_username=telegram_username,
        )
    except Exception:
        raise
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


def _parse_age_range(value: str) -> tuple[int, int]:
    """Parse age range input like '18-35'."""

    parts = value.replace(" ", "").split("-")
    if len(parts) != 2:
        raise ValueError("Invalid range")
    min_age = int(parts[0])
    max_age = int(parts[1])
    if min_age <= 0 or max_age <= 0:
        raise ValueError("Invalid ages")
    if max_age < min_age:
        raise ValueError("Invalid range")
    return min_age, max_age
