"""Advertiser registration flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.start import ADVERTISER_LABEL
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
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


ADVERTISER_FLOW_TYPE = "advertiser_registration"
ADVERTISER_CHOOSE_ACTION_TEXT = "Выберите действие:"
ADVERTISER_INTRO_TEXT = (
    "Вы выбрали роль «Мне нужны UGC‑креаторы».\n"
    "Давайте создадим профиль, чтобы вы могли размещать заказы."
)


@router.message(Command("advertiser"))
@router.message(lambda msg: (msg.text or "").strip() == ADVERTISER_LABEL)
async def choose_advertiser_role(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Мне нужны UGC‑креаторы': persist role, show menu or reg."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    await handle_role_choice(
        incoming,
        messenger_client,
        user_role_service,
        AiogramStateStore(state),
        profile_getter=profile_service.get_advertiser_profile,
        choose_action_text=ADVERTISER_CHOOSE_ACTION_TEXT,
        intro_text=ADVERTISER_INTRO_TEXT,
        menu_keyboard=advertiser_menu_keyboard,
        start_keyboard=advertiser_start_keyboard,
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


async def _ask_name(
    message: Message,
    messenger_client: MessengerClient,
    state_store: AiogramStateStore,
    event_adapter: MessengerEventAdapter,
) -> None:
    """Send name prompt and set state to name."""
    incoming = event_adapter.from_message(message)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Как вас зовут?",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.name.state)


@router.message(
    lambda msg: (msg.text or "").strip() == ADVERTISER_START_BUTTON_TEXT
)
async def handle_advertiser_start(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle 'Начать' after advertiser role: menu or start registration."""
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

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите действие:",
            keyboard=advertiser_menu_keyboard(),
        )
        return

    await state_store.update_data(user_id=user.user_id)
    if user.username and len(user.username.strip()) >= 2:
        await state_store.update_data(name=user.username)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Укажите номер телефона для связи по заказу.\n"
                "Пример: 89001110777"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(AdvertiserRegistrationStates.phone.state)
    else:
        await _ask_name(
            message,
            messenger_client,
            state_store,
            event_adapter,
        )


@router.message(AdvertiserRegistrationStates.name)
async def handle_name(
    message: Message,
    state: FSMContext,
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
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Укажите номер телефона для связи по заказу.\nПример: 89001110777"
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(AdvertiserRegistrationStates.phone.state)


@router.message(AdvertiserRegistrationStates.phone)
async def handle_phone(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store phone and ask for city."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    phone = (incoming.text or "").strip()
    err = validate_phone(phone)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
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


def _agreements_keyboard() -> Keyboard:
    """Keyboard with single 'Confirm agreement' button."""
    return Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
        resize=True,
        one_time=True,
    )


@router.message(AdvertiserRegistrationStates.site_link)
async def handle_site_link(
    message: Message,
    state: FSMContext,
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store site_link and show agreements step."""
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

    text = format_agreements_message(config)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=_agreements_keyboard(),
        parse_mode="HTML",
    )
    await state_store.set_state(AdvertiserRegistrationStates.agreements.state)


@router.message(AdvertiserRegistrationStates.agreements)
async def handle_agreements_confirm(
    message: Message,
    state: FSMContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """On 'Confirm agreement' create profile and show success."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    if (incoming.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Нажмите «Подтвердить согласие» для завершения регистрации.",
            keyboard=_agreements_keyboard(),
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
    name = data["name"]
    phone = data["phone"]
    brand = data["brand"]
    site_link = data.get("site_link")
    city = data.get("city")
    company_activity = data.get("company_activity")

    user = await user_role_service.get_user_by_id(user_id)
    if user is not None:
        await user_role_service.set_user(
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=name,
            role_chosen=False,
            telegram_username=None,
        )

    await advertiser_registration_service.register_advertiser(
        user_id=user_id,
        phone=phone,
        brand=brand,
        site_link=site_link,
        city=city,
        company_activity=company_activity,
    )

    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Теперь вы можете разместить заказ и найти UGC-креаторов.",
        keyboard=advertiser_menu_keyboard(),
    )
