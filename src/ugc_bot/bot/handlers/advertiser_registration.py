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
) -> None:
    """Send name prompt and set state to name."""
    await messenger_client.send_text(
        chat_id=chat_id,
        text="Как вас зовут?",
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
        await messenger_client.send_text(
            chat_id=chat_id,
            text=(
                "Укажите номер телефона для связи по заказу.\n"
                "Нажмите кнопку ниже или введите номер вручную "
                "(пример: 89001110777)."
            ),
            keyboard=phone_request_keyboard(texts),
        )
        await state_store.set_state(AdvertiserRegistrationStates.phone.state)
    else:
        await _ask_name_for_chat(chat_id, messenger_client, state_store)


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
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_phone_request",
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
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return
    state_store = AiogramStateStore(state)
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_support",
            "btn_phone_request",
            "msg_choose_action",
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
    name = (incoming.text or "").strip()
    err = validate_name(name)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(name=name)
    texts = await bot_texts_service.get_many(
        ["btn_phone_request"], config.market.default_locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Укажите номер телефона для связи по заказу.\n"
            "Нажмите кнопку ниже или введите номер вручную "
            "(пример: 89001110777)."
        ),
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
    phone = (incoming.contact_phone or incoming.text or "").strip()
    err = validate_phone(phone)
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
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.city.state)


@router.message(AdvertiserRegistrationStates.city)
async def handle_city(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store city and ask for brand."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    city = (incoming.text or "").strip() or None
    err = validate_city(city, required=False)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(city=city)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Название вашего бренда / компании / бизнеса:",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.brand.state)


@router.message(AdvertiserRegistrationStates.brand)
async def handle_brand(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store brand and ask for company activity."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    brand = (incoming.text or "").strip()
    err = validate_brand(brand)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(brand=brand)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Чем занимается ваша компания?",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(
        AdvertiserRegistrationStates.company_activity.state
    )


@router.message(AdvertiserRegistrationStates.company_activity)
async def handle_company_activity(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store company activity and ask for site link."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    company_activity = (incoming.text or "").strip() or None
    err = validate_company_activity(company_activity)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(company_activity=company_activity)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Ссылка на сайт, продукт или соцсети бренда:",
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
    site_link = (incoming.text or "").strip() or None
    err = validate_site_link(site_link)
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
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
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

    texts = await bot_texts_service.get_many(
        ["btn_confirm_agreement"], config.market.default_locale
    )
    text = format_agreements_message(config)
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
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Регистрация прервана. Чтобы завершить, откройте «Мой профиль» "
                "и подтвердите согласие."
            ),
            keyboard=flow_keyboard_remove(),
        )
        return
    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
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
        text=msg_done or "Теперь вы можете разместить заказ.",
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
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново.",
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
        text=msg_done or "Теперь вы можете разместить заказ.",
        keyboard=advertiser_menu_keyboard(texts),
    )
