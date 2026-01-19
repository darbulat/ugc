"""Handlers for offer responses."""

from __future__ import annotations

import logging
from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserRole, UserStatus


router = Router()
logger = logging.getLogger(__name__)


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer:")
)
async def handle_offer_response(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    offer_response_service: OfferResponseService,
) -> None:
    """Handle blogger response to offer."""

    if callback.from_user is None:
        return

    user = user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None or user.role not in {UserRole.BLOGGER, UserRole.BOTH}:
        await callback.answer("Вы не можете откликаться на офферы.")
        return
    if user.status == UserStatus.BLOCKED:
        await callback.answer("Заблокированные пользователи не могут откликаться.")
        return
    if user.status == UserStatus.PAUSE:
        await callback.answer("Пользователи на паузе не могут откликаться.")
        return
    if user.status == UserStatus.BLOCKED:
        await callback.answer("Заблокированные пользователи не могут откликаться.")
        return
    if user.status == UserStatus.PAUSE:
        await callback.answer("Пользователи на паузе не могут откликаться.")
        return

    raw = callback.data.split("offer:", 1)[-1] if callback.data else ""
    try:
        order_id = UUID(raw)
    except ValueError:
        await callback.answer("Неверный идентификатор заказа.")
        return

    order = offer_response_service.order_repo.get_by_id(order_id)
    if order is None:
        await callback.answer("Заказ не найден.")
        return
    if order.status != OrderStatus.ACTIVE:
        await callback.answer("Заказ не активен.")
        return
    if offer_response_service.response_repo.exists(order_id, user.user_id):
        await callback.answer("Вы уже откликались на этот заказ.")
        return
    if (
        offer_response_service.response_repo.count_by_order(order_id)
        >= order.bloggers_needed
    ):
        await callback.answer("Лимит откликов по заказу достигнут.")
        return

    try:
        offer_response_service.respond(order_id, user.user_id)
    except OrderCreationError as exc:
        logger.warning(
            "Offer response rejected",
            extra={"user_id": user.user_id, "reason": str(exc)},
        )
        await callback.answer(str(exc))
        return
    except Exception:
        logger.exception(
            "Unexpected offer response error",
            extra={"user_id": user.user_id},
        )
        await callback.answer("Произошла ошибка. Попробуйте позже.")
        return

    await callback.answer("Отклик принят! Ожидайте связи от рекламодателя.")
    if callback.message:
        await callback.message.answer(
            "Ваш отклик сохранен. Рекламодатель свяжется с вами."
        )
