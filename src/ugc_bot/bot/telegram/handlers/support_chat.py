"""Telegram handler for support group replies → forward back to Max user."""

import logging

from aiogram import F, Router
from aiogram.types import Message

from ugc_bot.application.services.support_service import SupportService
from ugc_bot.config import AppConfig

router = Router()

logger = logging.getLogger(__name__)


@router.message(F.reply_to_message, F.chat.type.in_({"group", "supergroup"}))
async def handle_support_group_reply(
    message: Message,
    config: AppConfig,
    support_service: SupportService,
    max_messenger_client: object | None = None,
) -> None:
    """Route operator replies from Telegram support group back to Max user."""
    support_chat_id = (config.market.support_chat_id or "").strip()
    if not support_chat_id:
        return

    # Only process messages from the configured support group
    if str(message.chat.id) != support_chat_id:
        return

    reply_to = message.reply_to_message
    if reply_to is None:
        return

    # Look up which Max user this reply is for
    user_chat_id = await support_service.find_user_by_support_reply(
        reply_to.message_id
    )
    if user_chat_id is None:
        return

    if max_messenger_client is None:
        logger.error("max_messenger_client not available for support reply")
        return

    reply_text = (message.text or "").strip()
    if not reply_text:
        return

    try:
        await max_messenger_client.send_text(
            chat_id=user_chat_id,
            text=f"Ответ от поддержки:\n\n{reply_text}",
        )
    except Exception:
        logger.exception(
            "Failed to send support reply to Max user %s", user_chat_id
        )
        return

    # Confirm delivery in the support group
    try:
        await message.reply("✅ Ответ доставлен пользователю")
    except Exception:
        logger.debug("Could not send delivery confirmation in support group")
