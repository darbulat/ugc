"""Handlers for admin order moderation via Telegram (activate button)."""

import contextlib
import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.messenger.dto import IncomingCallback
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.admin_notification_service import (
    MOD_ACTIVATE_CALLBACK_PREFIX,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import resolve_messenger_dependencies
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.session import TransactionManagerProtocol

logger = logging.getLogger(__name__)

router = Router()


def _parse_order_id_from_callback(data: str) -> UUID | None:
    """Parse order_id from mod_activate callback. None if invalid."""
    if not data or not data.startswith(MOD_ACTIVATE_CALLBACK_PREFIX):
        return None
    order_id_raw = data[len(MOD_ACTIVATE_CALLBACK_PREFIX) :]
    if len(order_id_raw) != 32:
        return None
    try:
        return UUID(hex=order_id_raw)
    except ValueError:
        return None


async def _remove_moderation_keyboard(
    callback: IncomingCallback,
    messenger_client: MessengerClient | None = None,
) -> None:
    """Remove inline keyboard from moderation message after activation."""
    if messenger_client is None:
        return
    if not callback.message_id:
        return
    with contextlib.suppress(Exception):
        await messenger_client.edit_reply_markup(
            chat_id=callback.chat_id,
            message_id=callback.message_id,
            keyboard=None,
        )


async def _validate_and_get_order(
    callback: IncomingCallback,
    user_role_service: UserRoleService,
    order_repo: OrderRepository,
    session: object,
) -> tuple[str | None, Order | None]:
    """Validate user/admin and load order. Returns (error_msg, order)."""
    external_id = callback.user.external_id
    if not external_id:
        return ("Ошибка: пользователь не определён.", None)

    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=callback.user.messenger_type,
    )
    if user is None:
        return ("Пользователь не найден.", None)
    if not user.admin:
        return ("Доступ запрещён.", None)

    order_id = _parse_order_id_from_callback(callback.data or "")
    if order_id is None:
        return ("Неверный формат идентификатора заказа.", None)

    order = await order_repo.get_by_id(order_id, session=session)
    if order is None:
        return ("Заказ не найден.", None)
    if order.status != OrderStatus.PENDING_MODERATION:
        return ("Заказ уже обработан.", None)

    return (None, order)


@router.callback_query(
    lambda c: c.data and c.data.startswith(MOD_ACTIVATE_CALLBACK_PREFIX)
)
async def handle_moderate_activate(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    content_moderation_service: ContentModerationService,
    order_repo: OrderRepository,
    outbox_publisher: OutboxPublisher,
    transaction_manager: TransactionManagerProtocol,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle admin click on 'Activate' button for order moderation."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    async with transaction_manager.transaction() as session:
        err, order = await _validate_and_get_order(
            incoming, user_role_service, order_repo, session
        )
        if err:
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id, text=err
            )
            return
        assert order is not None

        if _order_has_banned_content(order, content_moderation_service):
            msg = _format_banned_content_message(
                order, content_moderation_service
            )
            await messenger_client.answer_callback(
                callback_id=incoming.callback_id,
                text=msg,
                show_alert=True,
            )
            return

        await outbox_publisher.publish_order_activation(order, session=session)

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="Заказ активирован, уходит блогерам.",
    )
    await _remove_moderation_keyboard(incoming, messenger_client)


def _order_has_banned_content(
    order: Order,
    content_moderation: ContentModerationService,
) -> bool:
    """Check if order contains banned content."""
    return content_moderation.order_contains_banned_content(
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=order.barter_description,
        content_usage=order.content_usage,
        geography=order.geography,
    )


def _format_banned_content_message(
    order: Order,
    content_moderation: ContentModerationService,
) -> str:
    """Format error message listing banned matches."""
    matches = content_moderation.get_order_banned_matches(
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=order.barter_description,
        content_usage=order.content_usage,
        geography=order.geography,
    )
    joined = ", ".join(matches)
    return f"Запрещённый контент: {joined}. Отредактируйте в админке."
