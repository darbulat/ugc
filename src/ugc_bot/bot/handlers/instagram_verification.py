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
    blogger_verification_sent_inline_keyboard,
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


def _format_verification_instruction(
    template: str, admin_instagram_username: str
) -> str:
    """Format verification instruction with escaped URL for HTML.

    Uses HTML parse mode so the URL (e.g. with underscores) does not break
    Telegram entity parsing. Template must contain {url} placeholder.
    """
    base = "https://www.instagram.com/"
    username = (admin_instagram_username or "usemycontent").lstrip("@")
    url = f"{base}{username}/"
    url_escaped = html.escape(url, quote=True)
    return template.format(url=url_escaped)


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
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start Instagram verification: instruction then code."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_instagram_blocked",
            "msg_instagram_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found_start", ""),
        blocked_msg=allow_msgs.get("msg_instagram_blocked", ""),
        pause_msg=allow_msgs.get("msg_instagram_pause", ""),
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_empty = await bot_texts_service.get(
            "msg_profile_empty_creator", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_empty,
        )
        return

    if blogger_profile.confirmed:
        msg_confirmed = await bot_texts_service.get(
            "msg_instagram_already_confirmed", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_confirmed,
        )
        return

    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    await state_store.clear()

    instruction_template = await bot_texts_service.get(
        "msg_instagram_verify_instruction", locale
    )
    instruction = _format_verification_instruction(
        instruction_template, config.instagram.admin_instagram_username
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=instruction, parse_mode="HTML"
    )
    code_escaped = html.escape(verification.code)
    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=f"<code>{code_escaped}</code>",
        parse_mode="HTML",
        keyboard=blogger_verification_sent_inline_keyboard(texts),
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
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start Instagram verification from profile inline menu."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_instagram_blocked",
            "msg_instagram_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_user_not_found_start", ""),
        blocked_msg=allow_msgs.get("msg_instagram_blocked", ""),
        pause_msg=allow_msgs.get("msg_instagram_pause", ""),
    )
    if user is None:
        return
    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_empty = await bot_texts_service.get(
            "msg_profile_empty_creator", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_empty,
        )
        return
    if blogger_profile.confirmed:
        msg_confirmed = await bot_texts_service.get(
            "msg_instagram_already_confirmed", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_confirmed,
        )
        return
    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    state_store = AiogramStateStore(state)
    await state_store.clear()
    instruction_template = await bot_texts_service.get(
        "msg_instagram_verify_instruction", locale
    )
    instruction = _format_verification_instruction(
        instruction_template, config.instagram.admin_instagram_username
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=instruction, parse_mode="HTML"
    )
    code_escaped = html.escape(verification.code)
    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=f"<code>{code_escaped}</code>",
        parse_mode="HTML",
        keyboard=blogger_verification_sent_inline_keyboard(texts),
    )
