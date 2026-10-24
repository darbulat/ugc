"""Advertiser registration flow handlers for Max messenger."""

import logging
from uuid import UUID

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_AGREE,
    CALLBACK_ADV_START,
    CALLBACK_ROLE_ADVERTISER,
    advertiser_menu_inline_keyboard,
    advertiser_start_keyboard,
    confirm_agreement_inline_keyboard,
    flow_inline_keyboard_location_request,
    flow_inline_keyboard_phone_request,
    flow_keyboard_remove,
)
from ugc_bot.bot.telegram.handlers.utils import (
    format_agreements_message,
    handle_role_choice,
    parse_user_id_from_state,
    resolve_city_name_from_location,
)
from ugc_bot.bot.telegram.validators import (
    VALIDATOR_ERR_KEYS,
    normalize_url,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_name,
    validate_phone,
    validate_site_link,
)
from ugc_bot.config import AppConfig

router = MaxRouter()
logger = logging.getLogger(__name__)

# FSM state names for advertiser registration
STATE_ADV_NAME = "adv_name"
STATE_ADV_PHONE = "adv_phone"
STATE_ADV_CITY = "adv_city"
STATE_ADV_BRAND = "adv_brand"
STATE_ADV_ACTIVITY = "adv_activity"
STATE_ADV_SITE = "adv_site"
STATE_ADV_AGREEMENTS = "adv_agreements"

ADVERTISER_CHOOSE_ACTION_TEXT = "Выберите действие:"
ADVERTISER_INTRO_TEXT = (
    "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
    "Давайте создадим профиль, чтобы вы могли размещать заказы."
)


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
) -> None:
    """Remove inline keyboard from the message that triggered the callback."""
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )


# --- Role selection ---


@router.message(lambda m: bool(m.text and m.text.startswith("/advertiser")))
async def advertiser_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /advertiser command — show menu or registration prompt."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    profile_service: ProfileService = deps["profile_service"]
    user_role_service: UserRoleService = deps["user_role_service"]

    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_advertiser_start",
            "msg_choose_action",
            "btn_partner_program",
        ],
        locale,
    )
    choose_action_text = texts.get(
        "msg_choose_action", ADVERTISER_CHOOSE_ACTION_TEXT
    )
    intro_text = await bot_texts_service.get("msg_advertiser_intro", locale)
    if not intro_text:
        intro_text = ADVERTISER_INTRO_TEXT

    await handle_role_choice(
        incoming,  # type: ignore[arg-type]
        messenger_client,
        user_role_service,
        state_store,
        profile_getter=profile_service.get_advertiser_profile,
        choose_action_text=choose_action_text,
        intro_text=intro_text,
        menu_keyboard=advertiser_menu_inline_keyboard,
        start_keyboard=advertiser_start_keyboard,
        texts=texts,
    )


@router.callback(lambda c: c.data == CALLBACK_ROLE_ADVERTISER)
async def handle_role_advertiser_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle advertiser role selection via inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(incoming, messenger_client)

    profile_service: ProfileService = deps["profile_service"]
    user_role_service: UserRoleService = deps["user_role_service"]

    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_advertiser_start",
            "msg_choose_action",
            "btn_partner_program",
        ],
        locale,
    )
    choose_action_text = texts.get(
        "msg_choose_action", ADVERTISER_CHOOSE_ACTION_TEXT
    )
    intro_text = await bot_texts_service.get("msg_advertiser_intro", locale)
    if not intro_text:
        intro_text = ADVERTISER_INTRO_TEXT

    await handle_role_choice(
        incoming,  # type: ignore[arg-type]
        messenger_client,
        user_role_service,
        state_store,
        profile_getter=profile_service.get_advertiser_profile,
        choose_action_text=choose_action_text,
        intro_text=intro_text,
        menu_keyboard=advertiser_menu_inline_keyboard,
        start_keyboard=advertiser_start_keyboard,
        texts=texts,
    )


# --- Start advertiser registration ---


@router.callback(lambda c: c.data == CALLBACK_ADV_START)
async def handle_advertiser_start_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Handle 'Start' after advertiser role via inline button."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard(incoming, messenger_client)

    user_role_service: UserRoleService = deps["user_role_service"]
    profile_service: ProfileService = deps["profile_service"]

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

    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_phone_request",
            "msg_choose_action",
            "msg_whats_your_name",
            "msg_phone_request",
            "btn_partner_program",
        ],
        locale,
    )

    user_id = getattr(user, "user_id", None)
    if not isinstance(user_id, UUID):
        return
    username = getattr(user, "username", None) or ""

    advertiser = await profile_service.get_advertiser_profile(user_id)
    if advertiser is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=texts.get("msg_choose_action", ADVERTISER_CHOOSE_ACTION_TEXT),
            keyboard=advertiser_menu_inline_keyboard(texts),
        )
        return

    await state_store.update_data(
        user_id=str(user_id),
        user_country=getattr(user, "country", None),
    )

    if username and len(username.strip()) >= 2:
        await state_store.update_data(name=username)
        phone_prompt = texts.get("msg_phone_request", "")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=phone_prompt,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(STATE_ADV_PHONE)
    else:
        name_prompt = texts.get("msg_whats_your_name", "Как вас зовут?")
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=name_prompt,
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(STATE_ADV_NAME)


# --- FSM step handlers ---


@router.message_in_state(STATE_ADV_NAME)
async def handle_name(incoming: IncomingMessage, deps: dict) -> None:
    """Store name and ask for phone."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    name = (incoming.text or "").strip()
    err = validate_name(name, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(name=name)
    texts = await bot_texts_service.get_many(
        ["btn_phone_request", "msg_phone_request"], locale
    )
    phone_prompt = texts.get("msg_phone_request", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=phone_prompt,
        keyboard=flow_inline_keyboard_phone_request(texts),
    )
    await state_store.set_state(STATE_ADV_PHONE)


@router.message_in_state(STATE_ADV_PHONE)
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
        ["msg_what_city", "btn_location_request"], locale
    )
    msg_city = city_texts.get("msg_what_city", "")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_city,
        keyboard=flow_inline_keyboard_location_request(city_texts),
    )
    await state_store.set_state(STATE_ADV_CITY)


@router.message_in_state(STATE_ADV_CITY)
async def handle_city(incoming: IncomingMessage, deps: dict) -> None:
    """Store city (text or location) and ask for brand."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )

    # Handle shared location via reverse geocoding.
    # Advertiser profile stores only city (no region/country/geometry)
    # because advertiser_registration_service uses a flat city field.
    if incoming.location_lat is not None and incoming.location_lon is not None:
        city = await resolve_city_name_from_location(
            incoming.location_lat,
            incoming.location_lon,
            deps["blogger_registration_service"],
        )
        if city is None:
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
        validator_texts = await bot_texts_service.get_many(
            list(VALIDATOR_ERR_KEYS), locale
        )
        city = (incoming.text or "").strip() or None
        err = validate_city(city, required=False, texts=validator_texts)
        if err is not None:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=err,
                keyboard=flow_keyboard_remove(),
            )
            return

    await state_store.update_data(city=city)
    msg_brand = await bot_texts_service.get("msg_brand_name", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_brand,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_ADV_BRAND)


@router.message_in_state(STATE_ADV_BRAND)
async def handle_brand(incoming: IncomingMessage, deps: dict) -> None:
    """Store brand and ask for company activity."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    brand = (incoming.text or "").strip()
    err = validate_brand(brand, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(brand=brand)
    msg_activity = await bot_texts_service.get("msg_company_activity", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_activity,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_ADV_ACTIVITY)


@router.message_in_state(STATE_ADV_ACTIVITY)
async def handle_company_activity(
    incoming: IncomingMessage, deps: dict
) -> None:
    """Store company activity and ask for site link."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    company_activity = (incoming.text or "").strip() or None
    err = validate_company_activity(company_activity, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(company_activity=company_activity)
    msg_link = await bot_texts_service.get("msg_brand_link", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_link,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(STATE_ADV_SITE)


@router.message_in_state(STATE_ADV_SITE)
async def handle_site_link(incoming: IncomingMessage, deps: dict) -> None:
    """Store site_link, save profile, and show agreements step."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    config: AppConfig = deps["config"]
    advertiser_registration_service: AdvertiserRegistrationService = deps[
        "advertiser_registration_service"
    ]

    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    site_link = (incoming.text or "").strip() or None
    err = validate_site_link(site_link, texts=validator_texts)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(
        site_link=normalize_url(site_link) if site_link else None
    )

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

    await advertiser_registration_service.save_advertiser_before_agreement(
        user_id=user_id,
        phone=data["phone"],
        brand=data["brand"],
        site_link=data.get("site_link"),
        city=data.get("city"),
        company_activity=data.get("company_activity"),
        display_name=data.get("name"),
    )

    agreement_keys = [
        "btn_confirm_agreement",
        "msg_agreements_intro_default",
        "msg_label_offer",
        "msg_label_privacy",
        "msg_label_consent",
        "msg_confirm_docs_fallback",
    ]
    texts = await bot_texts_service.get_many(agreement_keys, locale)
    text = format_agreements_message(
        config, texts=texts, country_code=data.get("user_country")
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=confirm_agreement_inline_keyboard(CALLBACK_ADV_AGREE, texts),
        parse_mode="HTML",
    )
    await state_store.set_state(STATE_ADV_AGREEMENTS)


@router.callback_in_state(
    STATE_ADV_AGREEMENTS, lambda c: c.data == CALLBACK_ADV_AGREE
)
async def handle_agreements_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """On inline 'Confirm agreement' finalize advertiser registration."""
    messenger_client, state_store, bot_texts_service, locale = _get_services(
        deps
    )
    advertiser_registration_service: AdvertiserRegistrationService = deps[
        "advertiser_registration_service"
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

    await advertiser_registration_service.confirm_advertiser_agreement(
        user_id=user_id,
    )
    await state_store.clear()

    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_partner_program",
        ],
        locale,
    )
    msg_done = await bot_texts_service.get("msg_after_registration", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_done,
        keyboard=advertiser_menu_inline_keyboard(texts),
    )
