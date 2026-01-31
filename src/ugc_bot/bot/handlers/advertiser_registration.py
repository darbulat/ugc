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
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    ADVERTISER_START_BUTTON_TEXT,
    advertiser_menu_keyboard,
    support_keyboard,
)
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

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
    await _ask_name(message, state)


@router.message(Command("register_advertiser"))
async def start_advertiser_registration(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
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
    await _ask_name(message, state)


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
