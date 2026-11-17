"""Read-only admin command and isolated callbacks for offer previews."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.creator_offer_preview import PREVIEW_CALLBACK_PREFIX
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.creator_offer_preview import CreatorOfferPreview
from ugc_bot.bot.telegram.handlers.utils import resolve_messenger_dependencies

router = Router()


@router.message(Command("preview_offer"))
async def preview_offer(
    message: Message,
    command: CommandObject,
    order_repo: OrderRepository,
    user_role_service: UserRoleService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    messenger, adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    await CreatorOfferPreview(
        order_repo, user_role_service, messenger, user_locale
    ).send(adapter.from_message(message), command.args or "")


@router.callback_query(
    lambda cb: (cb.data or "").startswith(PREVIEW_CALLBACK_PREFIX)
)
async def handle_offer_preview(
    callback: CallbackQuery,
    order_repo: OrderRepository,
    user_role_service: UserRoleService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    messenger, adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    await CreatorOfferPreview(
        order_repo, user_role_service, messenger, user_locale
    ).handle(adapter.from_callback(callback))
