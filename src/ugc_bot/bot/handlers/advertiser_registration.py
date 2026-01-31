"""Advertiser registration flow handlers."""

import logging
from uuid import UUID

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
from ugc_bot.bot.handlers.draft_prompts import get_draft_prompt
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    DRAFT_RESTORED_TEXT,
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
    advertiser_menu_keyboard,
    draft_choice_keyboard,
    support_keyboard,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


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

    if message.from_user is None:
        return

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Пользователь не найден. Начните с /start.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут регистрироваться.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут регистрироваться.")
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

    if message.from_user is None:
        return

    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Пользователь не найден. Начните с /start.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут регистрироваться.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут регистрироваться.")
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

    text = (message.text or "").strip()
    data = await state.get_data()
    user_id_raw = data.get("user_id")
    if user_id_raw is None:
        await state.clear()
        await message.answer("Сессия истекла. Начните снова.")
        return
    user_id = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw

    if text == RESUME_DRAFT_BUTTON_TEXT:
        draft = await fsm_draft_service.get_draft(user_id, ADVERTISER_FLOW_TYPE)
        if draft is None:
            await message.answer("Черновик уже использован. Начинаем с начала.")
            await _ask_name(message, state)
            return
        await fsm_draft_service.delete_draft(user_id, ADVERTISER_FLOW_TYPE)
        await state.update_data(**draft.data)
        await state.set_state(draft.state_key)
        prompt = get_draft_prompt(draft.state_key, draft.data)
        await message.answer(
            f"{DRAFT_RESTORED_TEXT}\n\n{prompt}",
            reply_markup=support_keyboard(),
        )
        return

    if text == START_OVER_BUTTON_TEXT:
        await fsm_draft_service.delete_draft(user_id, ADVERTISER_FLOW_TYPE)
        await _ask_name(message, state)
        return

    await message.answer(
        "Выберите «Продолжить» или «Начать заново».",
        reply_markup=draft_choice_keyboard(),
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
    user_id_raw = data["user_id"]
    user_id: UUID = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw
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
