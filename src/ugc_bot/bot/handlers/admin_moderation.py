"""Handlers for admin order moderation via Telegram (activate button)."""

import contextlib
import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.admin_notification_service import (
    MOD_ACTIVATE_CALLBACK_PREFIX,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import MessengerType, OrderStatus
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


async def _remove_moderation_keyboard(callback: CallbackQuery) -> None:
    """Remove inline keyboard from moderation message after activation."""
    if not callback.message or not hasattr(
        callback.message, "edit_reply_markup"
    ):
        return
    with contextlib.suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)


async def _validate_and_get_order(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    order_repo: OrderRepository,
) -> tuple[str | None, Order | None]:
    """Validate user/admin and load order. Returns (error_msg, order)."""
    external_id = str(callback.from_user.id) if callback.from_user else ""
    if not external_id:
        return ("Ошибка: пользователь не определён.", None)

    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        return ("Пользователь не найден.", None)
    if not user.admin:
        return ("Доступ запрещён.", None)

    order_id = _parse_order_id_from_callback(callback.data or "")
    if order_id is None:
        return ("Неверный формат идентификатора заказа.", None)

    order = await order_repo.get_by_id(order_id)
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
) -> None:
    """Handle admin click on 'Activate' button for order moderation."""
    err, order = await _validate_and_get_order(
        callback, user_role_service, order_repo
    )
    if err:
        await callback.answer(err)
        return
    assert order is not None

    if _order_has_banned_content(order, content_moderation_service):
        msg = _format_banned_content_message(order, content_moderation_service)
        await callback.answer(msg, show_alert=True)
        return

    async with transaction_manager.transaction() as session:
        order_in_tx = await order_repo.get_by_id(
            order.order_id, session=session
        )
        if order_in_tx is None:
            await callback.answer("Заказ не найден.")
            return
        if order_in_tx.status != OrderStatus.PENDING_MODERATION:
            await callback.answer("Заказ уже обработан.")
            return
        await outbox_publisher.publish_order_activation(
            order_in_tx, session=session
        )

    await callback.answer("Заказ активирован, уходит блогерам.")
    await _remove_moderation_keyboard(callback)


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
