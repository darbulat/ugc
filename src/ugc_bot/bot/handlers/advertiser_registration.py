"""Advertiser registration flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    advertiser_menu_keyboard,
    advertiser_start_keyboard,
    draft_choice_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.start import ADVERTISER_LABEL
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    handle_draft_choice,
    handle_role_choice,
    parse_user_id_from_state,
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
) -> None:
    """Handle 'Мне нужны UGC‑креаторы': persist role, show menu or reg."""

    await handle_role_choice(
        message,
        user_role_service,
        state,
        profile_getter=profile_service.get_advertiser_profile,
        choose_action_text=ADVERTISER_CHOOSE_ACTION_TEXT,
        intro_text=ADVERTISER_INTRO_TEXT,
        menu_keyboard=advertiser_menu_keyboard,
        start_keyboard=advertiser_start_keyboard,
    )


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    choosing_draft_restore = State()
    name = State()
    phone = State()
    city = State()
    brand = State()
    company_activity = State()
    site_link = State()
    agreements = State()


async def _ask_name(message: Message, state: FSMContext) -> None:
    """Send name prompt and set state to name."""
    await message.answer(
        "Как вас зовут?",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.name)


@router.message(
    lambda msg: (msg.text or "").strip() == ADVERTISER_START_BUTTON_TEXT
)
async def handle_advertiser_start(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle 'Начать' after advertiser role: menu or start registration."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is not None:
        await message.answer(
            "Выберите действие:",
            reply_markup=advertiser_menu_keyboard(),
        )
        return

    await state.update_data(user_id=user.user_id)
    draft = await fsm_draft_service.get_draft(
        user.user_id, ADVERTISER_FLOW_TYPE
    )
    if draft is not None:
        await message.answer(
            DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard()
        )
        await state.set_state(
            AdvertiserRegistrationStates.choosing_draft_restore
        )
        return
    if user.username and len(user.username.strip()) >= 2:
        await state.update_data(name=user.username)
        await message.answer(
            "Укажите номер телефона для связи по заказу.\nПример: 89001110777",
            reply_markup=flow_keyboard_remove(),
        )
        await state.set_state(AdvertiserRegistrationStates.phone)
    else:
        await _ask_name(message, state)


@router.message(AdvertiserRegistrationStates.choosing_draft_restore)
async def advertiser_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Continue or Start over when draft exists."""
    await handle_draft_choice(
        message,
        state,
        fsm_draft_service,
        flow_type=ADVERTISER_FLOW_TYPE,
        user_id_key="user_id",
        first_state=AdvertiserRegistrationStates.name,
        first_prompt="Как вас зовут?",
        first_keyboard=flow_keyboard_remove(),
        session_expired_msg="Сессия истекла. Начните снова.",
    )


@router.message(AdvertiserRegistrationStates.name)
async def handle_name(message: Message, state: FSMContext) -> None:
    """Store name and ask for phone."""

    name = (message.text or "").strip()
    err = validate_name(name)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(name=name)
    await message.answer(
        "Укажите номер телефона для связи по заказу.\nПример: 89001110777",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.phone)


@router.message(AdvertiserRegistrationStates.phone)
async def handle_phone(message: Message, state: FSMContext) -> None:
    """Store phone and ask for city."""

    phone = (message.text or "").strip()
    err = validate_phone(phone)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(phone=phone)
    await message.answer(
        "Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.city)


@router.message(AdvertiserRegistrationStates.city)
async def handle_city(message: Message, state: FSMContext) -> None:
    """Store city and ask for brand."""

    city = (message.text or "").strip() or None
    err = validate_city(city, required=False)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return
    await state.update_data(city=city)
    await message.answer(
        "Название вашего бренда / компании / бизнеса:",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.brand)


@router.message(AdvertiserRegistrationStates.brand)
async def handle_brand(message: Message, state: FSMContext) -> None:
    """Store brand and ask for company activity."""

    brand = (message.text or "").strip()
    err = validate_brand(brand)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(brand=brand)
    await message.answer(
        "Чем занимается ваша компания?",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.company_activity)


@router.message(AdvertiserRegistrationStates.company_activity)
async def handle_company_activity(message: Message, state: FSMContext) -> None:
    """Store company activity and ask for site link."""

    company_activity = (message.text or "").strip() or None
    err = validate_company_activity(company_activity)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return
    await state.update_data(company_activity=company_activity)
    await message.answer(
        "Ссылка на сайт, продукт или соцсети бренда:",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(AdvertiserRegistrationStates.site_link)


def _agreements_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard with single 'Confirm agreement' button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.message(AdvertiserRegistrationStates.site_link)
async def handle_site_link(
    message: Message,
    state: FSMContext,
    config: AppConfig,
) -> None:
    """Store site_link and show agreements step."""

    site_link = (message.text or "").strip() or None
    err = validate_site_link(site_link)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return
    await state.update_data(
        site_link=normalize_url(site_link) if site_link else None
    )

    text = format_agreements_message(config)
    await message.answer(
        text,
        reply_markup=_agreements_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdvertiserRegistrationStates.agreements)


@router.message(AdvertiserRegistrationStates.agreements)
async def handle_agreements_confirm(
    message: Message,
    state: FSMContext,
    advertiser_registration_service: AdvertiserRegistrationService,
    user_role_service: UserRoleService,
) -> None:
    """On 'Confirm agreement' create profile and show success."""

    if (message.text or "").strip() != CONFIRM_AGREEMENT_BUTTON_TEXT:
        await message.answer(
            "Нажмите «Подтвердить согласие» для завершения регистрации.",
            reply_markup=_agreements_keyboard(),
        )
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer("Сессия истекла. Начните заново.")
        await state.clear()
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

    await state.clear()
    await message.answer(
        "Теперь вы можете разместить заказ и найти UGC-креаторов.",
        reply_markup=advertiser_menu_keyboard(),
    )
