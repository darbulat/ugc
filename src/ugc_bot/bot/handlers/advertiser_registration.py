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
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import advertiser_menu_keyboard, support_keyboard
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    contact = State()


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
    await message.answer(
        "Введите контактные данные для связи:",
        reply_markup=support_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.contact)


@router.message(AdvertiserRegistrationStates.contact)
async def handle_contact(
    message: Message,
    state: FSMContext,
    advertiser_registration_service: AdvertiserRegistrationService,
) -> None:
    """Store contact and create advertiser profile."""

    contact = (message.text or "").strip()
    if not contact:
        await message.answer(
            "Контакт не может быть пустым. Введите снова:",
            reply_markup=support_keyboard(),
        )
        return

    data = await state.get_data()
    # Convert user_id from string (Redis) back to UUID if needed
    user_id_raw = data["user_id"]
    user_id: UUID = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw

    # Middleware handles AdvertiserRegistrationError, UserNotFoundError, and other exceptions
    profile = await advertiser_registration_service.register_advertiser(
        user_id=user_id,
        contact=contact,
    )

    await state.clear()
    await message.answer(
        "Профиль рекламодателя создан.\n"
        f"Контакт: {profile.contact}\n"
        "Создать заказ: /create_order",
        reply_markup=advertiser_menu_keyboard(),
    )
