"""Instagram verification flow handlers."""

import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.filters import TextEqualsKey
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
    blogger_verification_sent_keyboard,
)
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

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
@router.message(TextEqualsKey("btn_confirm_instagram"))
async def start_verification(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    instagram_verification_service: InstagramVerificationService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start Instagram verification: instruction then code."""
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
        blocked_msg="Заблокированные не могут подтверждать аккаунт.",
        pause_msg="На паузе не могут подтверждать аккаунт.",
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Профиль не заполнен. «Создать профиль» или /creator",
        )
        return

    if blogger_profile.confirmed:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Ваш Instagram‑аккаунт уже подтвержден",
        )
        return

    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    await state_store.clear()

    instruction = _verification_instruction_text(
        config.instagram.admin_instagram_username
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=instruction, parse_mode="HTML"
    )
    code_escaped = html.escape(verification.code)
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=f"<code>{code_escaped}</code>",
        parse_mode="HTML",
        keyboard=blogger_verification_sent_keyboard(texts),
    )


@router.callback_query(lambda c: c.data == CALLBACK_PROFILE_CONFIRM_INSTAGRAM)
async def start_verification_from_profile_callback(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    instagram_verification_service: InstagramVerificationService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start Instagram verification from profile inline menu."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Начните с /start.",
        blocked_msg="Заблокированные не могут подтверждать аккаунт.",
        pause_msg="На паузе не могут подтверждать аккаунт.",
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Профиль не заполнен. «Создать профиль» или /creator",
        )
        return
    if blogger_profile.confirmed:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Ваш Instagram‑аккаунт уже подтвержден",
        )
        return
    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    state_store = AiogramStateStore(state)
    await state_store.clear()
    instruction = _verification_instruction_text(
        config.instagram.admin_instagram_username
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=instruction, parse_mode="HTML"
    )
    code_escaped = html.escape(verification.code)
    locale = config.market.default_locale
    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=f"<code>{code_escaped}</code>",
        parse_mode="HTML",
        keyboard=blogger_verification_sent_keyboard(texts),
    )
