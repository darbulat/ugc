"""Telegram payment handlers."""

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError  # noqa: F401 - used in except
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import get_user_and_ensure_allowed
from ugc_bot.bot.handlers.keyboards import advertiser_after_payment_keyboard
from ugc_bot.bot.handlers.security_warnings import (
    ADVERTISER_AFTER_PAYMENT_IMPORTANT,
    ADVERTISER_AFTER_PAYMENT_SUCCESS,
    ADVERTISER_AFTER_PAYMENT_WHAT_NEXT,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderStatus


router = Router()
logger = logging.getLogger(__name__)


async def send_order_invoice(
    message: Message,
    order_id: UUID,
    offer_text: str,
    price_value: float,
    config: AppConfig,
) -> None:
    """Send Telegram invoice for order."""

    if message.bot is None:
        return

    try:
        price_decimal = Decimal(str(price_value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation:
        await message.answer("Некорректная сумма заказа.")
        return

    price = int(price_decimal * 100)
    if price > 100_000_000:
        await message.answer(
            "Сумма заказа слишком большая для выставления счета в Telegram."
        )
        return

    try:
        await message.bot.send_invoice(
            chat_id=message.chat.id,
            title=f"Оплата заказа {order_id}",
            description=offer_text[:255],
            payload=str(order_id),
            provider_token=config.bot.telegram_provider_token,
            currency="RUB",
            prices=[
                LabeledPrice(
                    label=f"💳 Заплатить {int(price_value)} ₽",
                    amount=price,
                )
            ],
        )
    except Exception:
        logger.exception(
            "Failed to send invoice",
            extra={"order_id": str(order_id), "price_minor": price},
        )
        await message.answer("Не удалось создать счет. Попробуйте позже.")


@router.message(Command("pay_order"))
async def pay_order(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    payment_service: PaymentService,
    contact_pricing_service: ContactPricingService,
    config: AppConfig,
) -> None:
    """Send Telegram invoice for an order."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные пользователи не могут оплачивать заказы.",
        pause_msg="Пользователи на паузе не могут оплачивать заказы.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await message.answer(
            "Профиль рекламодателя не заполнен. Команда: /register_advertiser"
        )
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

    order = await payment_service.get_order(order_id)
    if order is None:
        await message.answer("Заказ не найден.")
        return
    if order.advertiser_id != user.user_id:
        await message.answer("Заказ не принадлежит рекламодателю.")
        return
    if order.status != OrderStatus.NEW:
        await message.answer("Заказ не в статусе NEW.")
        return

    contact_price = await contact_pricing_service.get_price(order.bloggers_needed)
    if contact_price is None:
        await message.answer(
            "Стоимость доступа к контактам не настроена. Свяжитесь с поддержкой."
        )
        return

    if not config.bot.telegram_provider_token:
        await message.answer("Платежный провайдер не настроен.")
        return

    await send_order_invoice(
        message=message,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
    )


@router.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery) -> None:
    """Confirm pre-checkout query from Telegram."""

    if pre_checkout_query.bot is None:
        return
    await pre_checkout_query.bot.answer_pre_checkout_query(
        pre_checkout_query_id=pre_checkout_query.id, ok=True
    )


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
    user_role_service: UserRoleService,
    payment_service: PaymentService,
) -> None:
    """Handle successful Telegram payment."""

    if message.successful_payment is None:
        return

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные пользователи не могут оплачивать заказы.",
        pause_msg="Пользователи на паузе не могут оплачивать заказы.",
    )
    if user is None:
        return

    payload = message.successful_payment.invoice_payload
    try:
        order_id = UUID(payload)
    except ValueError:
        await message.answer("Не удалось определить заказ.")
        return

    try:
        await payment_service.confirm_telegram_payment(
            user_id=user.user_id,
            order_id=order_id,
            provider_payment_charge_id=message.successful_payment.provider_payment_charge_id,
            total_amount=message.successful_payment.total_amount,
            currency=message.successful_payment.currency,
        )
    except (OrderCreationError, UserNotFoundError) as exc:
        # Record failed payment metric (middleware handles logging and user message)
        metrics_collector = None
        if hasattr(payment_service, "metrics_collector"):
            metrics_collector = payment_service.metrics_collector
        if metrics_collector:
            metrics_collector.record_payment_failed(
                order_id=str(order_id),
                reason=str(exc),
            )
        # Re-raise so middleware can handle it
        raise

    await message.answer(ADVERTISER_AFTER_PAYMENT_SUCCESS)
    await message.answer(ADVERTISER_AFTER_PAYMENT_WHAT_NEXT, parse_mode="Markdown")
    await message.answer(ADVERTISER_AFTER_PAYMENT_IMPORTANT, parse_mode="Markdown")
    await message.answer(
        "Выберите действие:",
        reply_markup=advertiser_after_payment_keyboard(),
    )
