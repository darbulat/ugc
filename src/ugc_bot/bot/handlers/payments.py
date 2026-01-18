"""Mock payment handlers."""

from __future__ import annotations

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserRole


router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("pay_order"))
async def mock_pay_order(
    message: Message,
    user_role_service: UserRoleService,
    payment_service: PaymentService,
) -> None:
    """Mock payment for an order."""

    if message.from_user is None:
        return

    user = user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None or user.role not in {UserRole.ADVERTISER, UserRole.BOTH}:
        await message.answer("Please choose role 'Я рекламодатель' first.")
        return

    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /pay_order <order_id>")
        return

    try:
        order_id = UUID(args[1])
    except ValueError:
        await message.answer("Неверный формат order_id.")
        return

    try:
        payment = payment_service.mock_pay(user.user_id, order_id)
    except (OrderCreationError, UserNotFoundError) as exc:
        logger.warning(
            "Mock payment failed",
            extra={"user_id": user.user_id, "reason": str(exc)},
        )
        await message.answer(f"Ошибка оплаты: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during mock payment",
            extra={"user_id": user.user_id},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return

    await message.answer(
        f"Оплата зафиксирована (mock). Заказ активирован.\nPayment ID: {payment.payment_id}"
    )
