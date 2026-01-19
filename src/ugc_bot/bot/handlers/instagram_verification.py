"""Instagram verification flow handlers."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus


router = Router()
logger = logging.getLogger(__name__)


class InstagramVerificationStates(StatesGroup):
    """States for Instagram verification."""

    waiting_sent = State()
    waiting_code = State()


@router.message(Command("verify_instagram"))
async def start_verification(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    instagram_verification_service: InstagramVerificationService,
) -> None:
    """Start Instagram verification flow."""

    if message.from_user is None:
        return

    user = user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None or user.role not in {UserRole.BLOGGER, UserRole.BOTH}:
        await message.answer("Please choose role 'Я блогер' first.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer(
            "Заблокированные пользователи не могут подтверждать аккаунт."
        )
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут подтверждать аккаунт.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут подтверждаться.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут подтверждаться.")
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
    await state.update_data(user_id=user.user_id, attempts=0)
    await message.answer(
        _verification_instruction(verification.code),
        reply_markup=_sent_keyboard(),
    )
    await state.set_state(InstagramVerificationStates.waiting_sent)


@router.message(lambda msg: msg.text == "Я отправил код")
async def sent_code(message: Message, state: FSMContext) -> None:
    """Ask user to paste the code received in Instagram."""

    if message.from_user is None:
        return

    await message.answer("Введите код, полученный в Instagram:")
    await state.set_state(InstagramVerificationStates.waiting_code)


@router.message(InstagramVerificationStates.waiting_code)
async def verify_code(
    message: Message,
    state: FSMContext,
    instagram_verification_service: InstagramVerificationService,
) -> None:
    """Verify code input and update profile."""

    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("Код не может быть пустым. Введите снова:")
        return

    data = await state.get_data()
    user_id = data["user_id"]
    attempts = int(data.get("attempts", 0))

    try:
        verified = instagram_verification_service.verify_code(user_id, code)
    except (BloggerRegistrationError, UserNotFoundError) as exc:
        logger.warning(
            "Instagram verification failed",
            extra={"user_id": user_id, "reason": str(exc)},
        )
        await message.answer(f"Ошибка проверки: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during instagram verification",
            extra={"user_id": user_id},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return

    if verified:
        await state.clear()
        await message.answer("Instagram подтверждён. Теперь вы можете получать офферы.")
        return

    attempts += 1
    if attempts >= 3:
        await state.update_data(attempts=0)
        await message.answer("Код введён неверно 3 раза. Генерируем новый код.")
        verification = instagram_verification_service.generate_code(user_id)
        await message.answer(
            _verification_instruction(verification.code),
            reply_markup=_sent_keyboard(),
        )
        await state.set_state(InstagramVerificationStates.waiting_sent)
        return

    await state.update_data(attempts=attempts)
    await message.answer("Код неверный или просрочен. Попробуйте ещё раз:")


def _sent_keyboard() -> ReplyKeyboardMarkup:
    """Build keyboard for confirmation action."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Я отправил код")]],
        resize_keyboard=True,
        one_time_keyboard=True,
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
