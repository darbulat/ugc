"""Mock payment handlers."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserRole, UserStatus


router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("pay_order"))
async def mock_pay_order(
    message: Message,
    user_role_service: UserRoleService,
    payment_service: PaymentService,
    offer_dispatch_service: OfferDispatchService,
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
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут оплачивать заказы.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут оплачивать заказы.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут оплачивать.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут оплачивать.")
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

    order = payment_service.order_repo.get_by_id(order_id)
    if order is None:
        await message.answer("Заказ не найден.")
        return
    if order.advertiser_id != user.user_id:
        await message.answer("Заказ не принадлежит рекламодателю.")
        return
    if order.status != OrderStatus.NEW:
        await message.answer("Заказ не в статусе NEW.")
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

    try:
        order = offer_dispatch_service.order_repo.get_by_id(payment.order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        advertiser = offer_dispatch_service.user_repo.get_by_id(order.advertiser_id)
        if advertiser is None:
            raise OrderCreationError("Advertiser not found.")
        advertiser_status = advertiser.status.value.upper()
        bloggers = offer_dispatch_service.dispatch(payment.order_id)
        if not bloggers:
            await message.answer("Нет доступных блогеров для рассылки.")
        for blogger in bloggers:
            if message.bot is None:
                break
            if blogger.external_id.isdigit():
                await message.bot.send_message(
                    chat_id=int(blogger.external_id),
                    text=offer_dispatch_service.format_offer(order, advertiser_status),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Готов снять UGC",
                                    callback_data=f"offer:{order.order_id}",
                                )
                            ]
                        ]
                    ),
                )
    except OrderCreationError as exc:
        await message.answer(f"Ошибка рассылки оффера: {exc}")
    await message.answer(
        f"Оплата зафиксирована (mock). Заказ активирован.\nPayment ID: {payment.payment_id}"
    )
