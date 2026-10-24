"""Polling/dispatcher fallback consumes reserved starts before signup."""

from aiogram import Bot, Router
from aiogram.types import Message, Update

from ugc_bot.infrastructure.messenger.telegram.messenger_linking import (
    intercept_reserved_link,
    reserved_link_text,
)

router = Router(name="messenger_linking")


@router.message(lambda message: reserved_link_text(message.text) is not None)
async def reserved_start(
    message: Message,
    bot: Bot,
    event_update: Update,
    messenger_linking_service=None,
) -> bool:
    return await intercept_reserved_link(
        event_update, bot, messenger_linking_service
    )
