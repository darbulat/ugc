"""Instagram verification flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("verify_instagram"))
async def start_verification(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    instagram_verification_service: InstagramVerificationService,
) -> None:
    """Start Instagram verification flow."""

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
        await message.answer(
            "Заблокированные пользователи не могут подтверждать аккаунт."
        )
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут подтверждать аккаунт.")
        return
    blogger_profile = profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await message.answer("Профиль блогера не заполнен. Команда: /register")
        return

    try:
        verification = instagram_verification_service.generate_code(user.user_id)
    except (BloggerRegistrationError, UserNotFoundError) as exc:
        logger.warning(
            "Instagram verification start failed",
            extra={"user_id": user.user_id, "reason": str(exc)},
        )
        await message.answer(f"Ошибка подтверждения: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during instagram verification start",
            extra={"user_id": user.user_id},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return
    await state.clear()
    await message.answer(
        _verification_instruction(verification.code),
    )


def _verification_instruction(code: str) -> str:
    """Format instruction for Instagram verification."""

    return (
        "Чтобы подтвердить, что Instagram-аккаунт принадлежит вам:\n"
        "1️⃣ Скопируйте код ниже\n"
        "2️⃣ Отправьте его в личные сообщения (Direct) вашего Instagram-аккаунта\n"
        "3️⃣ Вернитесь в бот и нажмите «Я отправил код»\n\n"
        f"Код: {code}\n\n"
        "⚠️ Если у вас нет доступа к Direct указанного Instagram-аккаунта, "
        "вы не сможете пройти подтверждение."
    )
