"""Advertiser registration flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    handle_draft_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    advertiser_menu_keyboard,
    draft_choice_keyboard,
    support_keyboard,
)


router = Router()
logger = logging.getLogger(__name__)


ADVERTISER_FLOW_TYPE = "advertiser_registration"


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    choosing_draft_restore = State()
    name = State()
    phone = State()
    brand = State()


async def _ask_name(message: Message, state: FSMContext) -> None:
    """Send name prompt and set state to name."""
    await message.answer(
        "Как вас зовут?",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.name)


@router.message(lambda msg: (msg.text or "").strip() == ADVERTISER_START_BUTTON_TEXT)
async def handle_advertiser_start(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle 'Начать' after advertiser role: show menu if profile exists, else start registration."""

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
    draft = await fsm_draft_service.get_draft(user.user_id, ADVERTISER_FLOW_TYPE)
    if draft is not None:
        await message.answer(DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard())
        await state.set_state(AdvertiserRegistrationStates.choosing_draft_restore)
        return
    await _ask_name(message, state)


@router.message(Command("register_advertiser"))
async def start_advertiser_registration(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Start advertiser registration flow."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут регистрироваться.",
        pause_msg="Пользователи на паузе не могут регистрироваться.",
    )
    if user is None:
        return

    await state.update_data(user_id=user.user_id)
    draft = await fsm_draft_service.get_draft(user.user_id, ADVERTISER_FLOW_TYPE)
    if draft is not None:
        await message.answer(DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard())
        await state.set_state(AdvertiserRegistrationStates.choosing_draft_restore)
        return
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
        first_keyboard=support_keyboard(),
        session_expired_msg="Сессия истекла. Начните снова.",
    )


@router.message(AdvertiserRegistrationStates.name)
async def handle_name(message: Message, state: FSMContext) -> None:
    """Store name and ask for phone."""

    name = (message.text or "").strip()
    if not name:
        await message.answer(
            "Имя не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(name=name)
    await message.answer(
        "Номер телефона для связи по заказу (пример: +7 900 000-00-00):",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.phone)


@router.message(AdvertiserRegistrationStates.phone)
async def handle_phone(message: Message, state: FSMContext) -> None:
    """Store phone and ask for brand."""

    phone = (message.text or "").strip()
    if not phone:
        await message.answer(
            "Номер телефона не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    await state.update_data(phone=phone)
    await message.answer(
        "Название вашего бренда / компании / бизнеса:",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.brand)


@router.message(AdvertiserRegistrationStates.brand)
async def handle_brand(
    message: Message,
    state: FSMContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> None:
    """Store brand and create advertiser profile."""

    brand = (message.text or "").strip()
    if not brand:
        await message.answer(
            "Название бренда не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer("Сессия истекла. Начните заново.")
        return
    name = data["name"]
    phone = data["phone"]

    await advertiser_registration_service.register_advertiser(
        user_id=user_id,
        name=name,
        phone=phone,
        brand=brand,
    )

    await state.clear()
    await message.answer(
        "Профиль рекламодателя создан.",
        reply_markup=advertiser_menu_keyboard(),
    )
