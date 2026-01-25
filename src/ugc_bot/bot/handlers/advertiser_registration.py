"""Advertiser registration flow handlers."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import advertiser_menu_keyboard, cancel_keyboard
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)


class AdvertiserRegistrationStates(StatesGroup):
    """States for advertiser registration."""

    instagram_url = State()
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

    user = user_role_service.get_user(
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

    # Check if user already has Instagram verification
    if user.confirmed:
        await state.update_data(user_id=user.user_id)
        await message.answer(
            "У вас уже есть подтвержденный Instagram. Введите контактные данные для связи:",
            reply_markup=cancel_keyboard(),
        )
        await state.set_state(AdvertiserRegistrationStates.contact)
        return

    # Check if user already has Instagram URL
    if user.instagram_url:
        await state.update_data(user_id=user.user_id)
        await message.answer(
            "У вас уже указан Instagram. Введите контактные данные для связи:",
            reply_markup=cancel_keyboard(),
        )
        await state.set_state(AdvertiserRegistrationStates.contact)
        return

    await state.update_data(user_id=user.user_id)
    await message.answer(
        "Введите Instagram URL (например: https://instagram.com/username):",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(AdvertiserRegistrationStates.instagram_url)


@router.message(AdvertiserRegistrationStates.instagram_url)
async def handle_instagram_url(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
) -> None:
    """Store Instagram URL and proceed to contact."""

    instagram_url = (message.text or "").strip()
    if not instagram_url:
        await message.answer(
            "Instagram URL не может быть пустым. Введите снова:",
            reply_markup=cancel_keyboard(),
        )
        return

    # Basic validation
    if "instagram.com" not in instagram_url.lower():
        await message.answer(
            "Пожалуйста, введите корректный Instagram URL (например: https://instagram.com/username):",
            reply_markup=cancel_keyboard(),
        )
        return

    data = await state.get_data()
    user_id_raw = data["user_id"]
    user_id = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw

    # Update user with Instagram URL
    user = user_role_service.get_user_by_id(user_id)
    if user:
        updated_user = user.__class__(
            user_id=user.user_id,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            instagram_url=instagram_url,
            confirmed=False,
        )
        user_role_service.user_repo.save(updated_user)

    await state.update_data(instagram_url=instagram_url)
    await message.answer(
        "Введите контактные данные для связи:",
        reply_markup=cancel_keyboard(),
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
            reply_markup=cancel_keyboard(),
        )
        return

    data = await state.get_data()
    # Convert user_id from string (Redis) back to UUID if needed
    user_id_raw = data["user_id"]
    user_id: UUID = UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw

    try:
        profile = advertiser_registration_service.register_advertiser(
            user_id=user_id,
            contact=contact,
        )
    except (AdvertiserRegistrationError, UserNotFoundError) as exc:
        logger.warning(
            "Advertiser registration failed",
            extra={"user_id": data.get("user_id"), "reason": str(exc)},
        )
        await message.answer(f"Ошибка регистрации: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during advertiser registration",
            extra={"user_id": data.get("user_id")},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(
        "Профиль рекламодателя создан.\n"
        f"Контакт: {profile.contact}\n"
        "Создать заказ: /create_order",
        reply_markup=advertiser_menu_keyboard(),
    )
