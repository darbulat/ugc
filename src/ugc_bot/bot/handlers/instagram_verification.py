"""Instagram verification flow handlers."""

import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import get_user_and_ensure_allowed
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_INSTAGRAM_BUTTON_TEXT,
    blogger_verification_sent_keyboard,
)
from ugc_bot.config import AppConfig


router = Router()
logger = logging.getLogger(__name__)


def _verification_instruction_text(admin_instagram_username: str) -> str:
    """Instruction text without code (code sent in separate message).

    Uses HTML parse mode so the URL (which may contain underscores in username)
    does not break Telegram entity parsing.
    """
    base = "https://www.instagram.com/"
    username = (admin_instagram_username or "usemycontent").lstrip("@")
    url = f"{base}{username}/"
    url_escaped = html.escape(url, quote=True)
    return (
        "<b>Чтобы подтвердить Instagram‑аккаунт, сделайте 3 шага:</b>\n\n"
        "1. Скопируйте код ниже\n"
        "2. Отправьте его в личные сообщения Instagram‑аккаунту UMC\n"
        "3. Дождитесь автоматического подтверждения\n\n"
        f'🔗 Instagram UMC: <a href="{url_escaped}">{url_escaped}</a>\n\n'
        "🔐 Ваш код (код действует 15 минут) 👇"
    )


@router.message(Command("verify_instagram"))
@router.message(lambda msg: (msg.text or "").strip() == CONFIRM_INSTAGRAM_BUTTON_TEXT)
async def start_verification(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    instagram_verification_service: InstagramVerificationService,
    config: AppConfig,
) -> None:
    """Start Instagram verification flow: instruction then code in separate message."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные пользователи не могут подтверждать аккаунт.",
        pause_msg="Пользователи на паузе не могут подтверждать аккаунт.",
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await message.answer(
            "Профиль не заполнен. Нажмите «Создать профиль» или команда: /register"
        )
        return

    verification = await instagram_verification_service.generate_code(user.user_id)
    await state.clear()

    instruction = _verification_instruction_text(
        config.instagram.admin_instagram_username
    )
    await message.answer(instruction, parse_mode="HTML")
    await message.answer(
        verification.code,
        reply_markup=blogger_verification_sent_keyboard(),
    )
