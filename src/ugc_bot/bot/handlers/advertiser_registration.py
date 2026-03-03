"""Advertiser registration flow handlers."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.messenger.dto import IncomingCallback
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_ADV_AGREE,
    CALLBACK_ADV_START,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    confirm_agreement_inline_keyboard,
    flow_keyboard_remove,
    phone_request_keyboard,
)
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    handle_role_choice,
    parse_user_id_from_state,
    resolve_messenger_dependencies,
)
from ugc_bot.bot.validators import (
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
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()
logger = logging.getLogger(__name__)


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


ADVERTISER_FLOW_TYPE = "advertiser_registration"
ADVERTISER_CHOOSE_ACTION_TEXT = "Выберите действие:"
ADVERTISER_INTRO_TEXT = (
    "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
    "Давайте создадим профиль, чтобы вы могли размещать заказы."
)


@router.message(Command("advertiser"))
@router.message(TextEqualsKey("btn_advertiser"))
async def choose_advertiser_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle advertiser role: persist role, show menu or reg."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_advertiser_start",
            "msg_choose_action",
        ],
        locale,
    )
    choose_action_text = await bot_texts_service.get(
        "msg_choose_action", locale
    )
    intro_text = await bot_texts_service.get("msg_advertiser_intro", locale)
    if not intro_text:
        intro_text = ADVERTISER_INTRO_TEXT
    await handle_role_choice(
        incoming,
        messenger_client,
        user_role_service,
        AiogramStateStore(state),
        profile_getter=profile_service.get_advertiser_profile,
        choose_action_text=choose_action_text or ADVERTISER_CHOOSE_ACTION_TEXT,
        intro_text=intro_text,
        menu_keyboard=advertiser_menu_keyboard,
        start_keyboard=advertiser_start_keyboard,
        texts=texts,
    )


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    name = State()
    phone = State()
    city = State()
    brand = State()
    company_activity = State()
    site_link = State()
    agreements = State()


async def _ask_name_for_chat(
    chat_id: str,
    messenger_client: MessengerClient,
    state_store: AiogramStateStore,
    name_prompt: str,
) -> None:
    """Send name prompt and set state to name."""
    await messenger_client.send_text(
        chat_id=chat_id,
        text=name_prompt,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.name.state)


async def _advertiser_start_impl(
    chat_id: str,
    state_store: AiogramStateStore,
    user: object,
    messenger_client: MessengerClient,
    profile_service: ProfileService,
    texts: dict[str, str],
) -> None:
    """Run advertiser start logic: show menu or start registration."""
    user_id = getattr(user, "user_id", None)
    if not isinstance(user_id, UUID):
        return
    username = getattr(user, "username", None) or ""
    advertiser = await profile_service.get_advertiser_profile(user_id)
    if advertiser is not None:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=texts.get("msg_choose_action", "Выберите действие:"),
            keyboard=advertiser_menu_keyboard(texts),
        )
        return
    await state_store.update_data(user_id=user_id)
    if username and len(username.strip()) >= 2:
        await state_store.update_data(name=username)
        phone_prompt = texts.get("msg_phone_request", "")
        await messenger_client.send_text(
            chat_id=chat_id,
            text=phone_prompt,
            keyboard=phone_request_keyboard(texts),
        )
        await state_store.set_state(AdvertiserRegistrationStates.phone.state)
    else:
        name_prompt = texts.get("msg_whats_your_name", "Как вас зовут?")
        await _ask_name_for_chat(
            chat_id, messenger_client, state_store, name_prompt
        )


@router.message(TextEqualsKey("btn_advertiser_start"))
async def handle_advertiser_start(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Начать' after advertiser role (message, e.g. from tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
        ],
        locale,
    )
    await _advertiser_start_impl(
        incoming.chat_id,
        state_store,
        user,
        messenger_client,
        profile_service,
        texts,
    )


@router.callback_query(lambda c: c.data == CALLBACK_ADV_START)
async def handle_advertiser_start_callback(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Начать' after advertiser role via inline button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    locale = config.market.default_locale
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
        ],
        locale,
    )
    await _advertiser_start_impl(
        incoming.chat_id,
        state_store,
        user,
        messenger_client,
        profile_service,
        texts,
    )


@router.message(AdvertiserRegistrationStates.name)
async def handle_name(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store name and ask for phone."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
        keyboard=phone_request_keyboard(texts),
    )
    await state_store.set_state(AdvertiserRegistrationStates.phone.state)


@router.message(AdvertiserRegistrationStates.phone)
async def handle_phone(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store phone and ask for city."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
    validator_texts = await bot_texts_service.get_many(
        list(VALIDATOR_ERR_KEYS), locale
    )
    phone = (incoming.contact_phone or incoming.text or "").strip()
    err = validate_phone(phone, texts=validator_texts)
    if err is not None:
        texts = await bot_texts_service.get_many(
            ["btn_phone_request"], config.market.default_locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=phone_request_keyboard(texts),
        )
        return

    await state_store.update_data(phone=phone)
    msg_city = await bot_texts_service.get("msg_what_city", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_city,
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.city.state)


@router.message(AdvertiserRegistrationStates.city)
async def handle_city(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store city and ask for brand."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
    await state_store.set_state(AdvertiserRegistrationStates.brand.state)


@router.message(AdvertiserRegistrationStates.brand)
async def handle_brand(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store brand and ask for company activity."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
    await state_store.set_state(
        AdvertiserRegistrationStates.company_activity.state
    )


@router.message(AdvertiserRegistrationStates.company_activity)
async def handle_company_activity(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store company activity and ask for site link."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
    await state_store.set_state(AdvertiserRegistrationStates.site_link.state)


@router.message(AdvertiserRegistrationStates.site_link)
async def handle_site_link(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    advertiser_registration_service: AdvertiserRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store site_link, save profile, and show agreements step."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
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
        locale = config.market.default_locale
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    try:
        await advertiser_registration_service.save_advertiser_before_agreement(
            user_id=user_id,
            phone=data["phone"],
            brand=data["brand"],
            site_link=data.get("site_link"),
            city=data.get("city"),
            company_activity=data.get("company_activity"),
            display_name=data.get("name"),
        )
    except Exception:
        raise

    agreement_keys = [
        "btn_confirm_agreement",
        "msg_agreements_intro_default",
        "msg_label_offer",
        "msg_label_privacy",
        "msg_label_consent",
        "msg_confirm_docs_fallback",
    ]
    texts = await bot_texts_service.get_many(
        agreement_keys, config.market.default_locale
    )
    text = format_agreements_message(config, texts=texts)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=confirm_agreement_inline_keyboard(CALLBACK_ADV_AGREE, texts),
        parse_mode="HTML",
    )
    await state_store.set_state(AdvertiserRegistrationStates.agreements.state)


@router.message(AdvertiserRegistrationStates.agreements)
async def handle_agreements_confirm(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    advertiser_registration_service: AdvertiserRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """On message 'Confirm agreement' confirm consent (e.g. from tests)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
    confirm_text = (
        await bot_texts_service.get("btn_confirm_agreement", locale)
    ).strip()
    if (incoming.text or "").strip() != confirm_text:
        await state_store.clear()
        msg_aborted = await bot_texts_service.get(
            "msg_registration_aborted", locale
        )
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
        ],
        locale,
    )
    msg_done = await bot_texts_service.get("msg_after_registration", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_done,
        keyboard=advertiser_menu_keyboard(texts),
    )


@router.callback_query(lambda c: c.data == CALLBACK_ADV_AGREE)
async def handle_advertiser_agreements_callback(
    callback: CallbackQuery,
    state: FSMContext,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    advertiser_registration_service: AdvertiserRegistrationService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """On inline 'Confirm agreement' confirm consent and show success."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    state_store = AiogramStateStore(state)
    current = await state.get_state()
    if current != AdvertiserRegistrationStates.agreements.state:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id)
        await _remove_inline_keyboard_from_callback(incoming, messenger_client)
        locale = config.market.default_locale
        msg_expired = await bot_texts_service.get("msg_session_expired", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_expired,
        )
        await state_store.clear()
        return

    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    await _remove_inline_keyboard_from_callback(incoming, messenger_client)
    await advertiser_registration_service.confirm_advertiser_agreement(
        user_id=user_id,
    )

    await state_store.clear()
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
        ],
        locale,
    )
    msg_done = await bot_texts_service.get("msg_after_registration", locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_done,
        keyboard=advertiser_menu_keyboard(texts),
    )
