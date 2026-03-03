"""Telegram payment handlers."""

import json
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery

from ugc_bot.application.errors import (  # noqa: F401 - used in except
    OrderCreationError,
    UserNotFoundError,
)
from ugc_bot.application.messenger.dto import Invoice, InvoiceItem
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
    PaymentProvider,
)
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_new_order,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    PAY_ORDER_CALLBACK_PREFIX,
    advertiser_after_payment_keyboard,
)
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)

router = Router()
logger = logging.getLogger(__name__)

DEFAULT_RECEIPT_SERVICE_DESCRIPTION = "Услуги платформы Use My Content"


def build_receipt_provider_data(
    total_amount: float,
    currency: str,
    receipt_description: str,
) -> str:
    """Build provider_data JSON for YooKassa receipt (54-FZ).

    Email is collected by Telegram via need_email and passed to provider.
    """
    amount_str = f"{total_amount:.2f}"
    receipt = {
        "receipt": {
            "items": [
                {
                    "description": receipt_description
                    or DEFAULT_RECEIPT_SERVICE_DESCRIPTION,
                    "quantity": 1,
                    "amount": {"value": amount_str, "currency": currency},
                    "vat_code": 2,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
            "internet": "true",
        }
    }
    return json.dumps(receipt, ensure_ascii=False)


async def send_order_invoice(
    incoming_message,
    messenger_client: MessengerClient,
    order_id: UUID,
    offer_text: str,
    price_value: float,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    receipt_description: str | None = None,
) -> None:
    """Send invoice for order with 54-FZ receipt (email via Telegram form)."""
    locale = config.market.default_locale

    if not incoming_message.chat_id:
        return

    try:
        price_decimal = Decimal(str(price_value)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    except InvalidOperation:
        msg_invalid = await bot_texts_service.get(
            "msg_invalid_order_amount", locale
        )
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id,
            text=msg_invalid,
        )
        return

    price = int(price_decimal * 100)
    if price > 100_000_000:
        msg_too_large = await bot_texts_service.get(
            "msg_order_amount_too_large", locale
        )
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id,
            text=msg_too_large,
        )
        return

    currency = config.market.payment_currency
    currency_symbol = config.market.currency_symbol
    receipt_desc = (
        (receipt_description or "").strip()
        or config.market.receipt_service_description
        or DEFAULT_RECEIPT_SERVICE_DESCRIPTION
    )
    provider_data = build_receipt_provider_data(
        total_amount=price_value,
        currency=currency,
        receipt_description=receipt_desc,
    )

    try:
        await messenger_client.send_invoice(
            chat_id=incoming_message.chat_id,
            invoice=Invoice(
                title=await bot_texts_service.get("msg_title_payment", locale),
                description=offer_text[:255],
                payload=str(order_id),
                provider_token=config.bot.telegram_provider_token,
                currency=currency,
                items=[
                    InvoiceItem(
                        label=(
                            f"💳 Заплатить {int(price_value)} {currency_symbol}"
                        ),
                        amount_minor=price,
                    )
                ],
                provider_data=provider_data,
                need_email=True,
                send_email_to_provider=True,
            ),
        )
    except Exception:
        logger.exception(
            "Failed to send invoice",
            extra={"order_id": str(order_id), "price_minor": price},
        )
        msg_failed = await bot_texts_service.get("msg_invoice_failed", locale)
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id,
            text=msg_failed,
        )


@router.message(Command("pay_order"))
async def pay_order(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    payment_service: PaymentService,
    contact_pricing_service: ContactPricingService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Send Telegram invoice for an order (email via payment form)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные пользователи не могут оплачивать заказы.",
        pause_msg="Пользователи на паузе не могут оплачивать заказы.",
    )
    if user is None:
        return

    locale = config.market.default_locale
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        msg_fill = await bot_texts_service.get(
            "msg_advertiser_profile_fill", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_fill,
        )
        return

    args = (incoming.text or "").split()
    if len(args) < 2:
        msg_usage = await bot_texts_service.get("msg_pay_order_usage", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_usage,
        )
        return

    try:
        order_id = UUID(args[1])
    except ValueError:
        msg_invalid_id = await bot_texts_service.get(
            "msg_invalid_order_id", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_invalid_id,
        )
        return

    order = await payment_service.get_order(order_id)
    if order is None:
        msg_not_found = await bot_texts_service.get(
            "msg_order_not_found", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_found,
        )
        return
    if order.advertiser_id != user.user_id:
        msg_not_yours = await bot_texts_service.get(
            "msg_order_not_yours", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_yours,
        )
        return
    if order.status != OrderStatus.NEW:
        msg_not_new = await bot_texts_service.get("msg_order_not_new", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_new,
        )
        return

    contact_price = await contact_pricing_service.get_price(
        order.bloggers_needed
    )
    if contact_price is None:
        msg_pricing = await bot_texts_service.get(
            "msg_pricing_not_configured", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_pricing,
        )
        return

    if not config.bot.telegram_provider_token:
        msg_provider = await bot_texts_service.get(
            "msg_payment_provider_not_configured", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_provider,
        )
        return

    receipt_desc = (
        await bot_texts_service.get("receipt_description", locale)
    ).strip() or None
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
        bot_texts_service=bot_texts_service,
        receipt_description=receipt_desc,
    )


@router.callback_query(
    lambda c: (
        c.data is not None and c.data.startswith(PAY_ORDER_CALLBACK_PREFIX)
    )
)
async def pay_order_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    payment_service: PaymentService,
    contact_pricing_service: ContactPricingService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Send Telegram invoice for an order from 'My orders' list button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные пользователи не могут оплачивать заказы.",
        pause_msg="Пользователи на паузе не могут оплачивать заказы.",
    )
    if user is None:
        return

    locale = config.market.default_locale
    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        msg_fill = await bot_texts_service.get(
            "msg_advertiser_profile_fill", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_fill,
        )
        return

    raw = (incoming.data or "").split(PAY_ORDER_CALLBACK_PREFIX, 1)[-1]
    try:
        order_id = UUID(raw)
    except ValueError:
        msg_invalid_fmt = await bot_texts_service.get(
            "msg_invalid_order_format", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_invalid_fmt,
        )
        return

    order = await payment_service.get_order(order_id)
    if order is None:
        msg_not_found = await bot_texts_service.get(
            "msg_order_not_found", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_found,
        )
        return
    if order.advertiser_id != user.user_id:
        msg_not_yours = await bot_texts_service.get(
            "msg_order_not_yours", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_yours,
        )
        return
    if order.status != OrderStatus.NEW:
        msg_not_new = await bot_texts_service.get("msg_order_not_new", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_not_new,
        )
        return

    contact_price = await contact_pricing_service.get_price(
        order.bloggers_needed
    )
    if contact_price is None:
        msg_pricing = await bot_texts_service.get(
            "msg_pricing_not_configured", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_pricing,
        )
        return

    if not config.bot.telegram_provider_token:
        msg_provider = await bot_texts_service.get(
            "msg_payment_provider_not_configured", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_provider,
        )
        return

    receipt_desc = (
        await bot_texts_service.get("receipt_description", locale)
    ).strip() or None
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
        bot_texts_service=bot_texts_service,
        receipt_description=receipt_desc,
    )


@router.pre_checkout_query()
async def pre_checkout_query_handler(
    pre_checkout_query: PreCheckoutQuery,
    payment_provider: PaymentProvider,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Confirm pre-checkout query from Telegram."""
    adapter = cast(
        MessengerEventAdapter,
        event_adapter if event_adapter is not None else TelegramEventAdapter(),
    )
    incoming = adapter.from_pre_checkout(pre_checkout_query)
    await payment_provider.confirm_pre_checkout(query_id=incoming.query_id)


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
    user_role_service: UserRoleService,
    payment_service: PaymentService,
    content_moderation_service: ContentModerationService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle successful Telegram payment."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    if incoming.successful_payment is None:
        return

    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные пользователи не могут оплачивать заказы.",
        pause_msg="Пользователи на паузе не могут оплачивать заказы.",
    )
    if user is None:
        return

    locale = config.market.default_locale
    payload = incoming.successful_payment.invoice_payload
    try:
        order_id = UUID(payload)
    except ValueError:
        msg_undetermined = await bot_texts_service.get(
            "msg_order_undetermined", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_undetermined,
        )
        return

    try:
        await payment_service.confirm_telegram_payment(
            user_id=user.user_id,
            order_id=order_id,
            provider_payment_charge_id=(
                incoming.successful_payment.provider_payment_charge_id
            ),
            total_amount=incoming.successful_payment.total_amount,
            currency=incoming.successful_payment.currency,
        )
    except (OrderCreationError, UserNotFoundError) as exc:
        # Record failed payment metric (middleware logs and shows user message)
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

    order = await payment_service.get_order(order_id)
    if order:
        await notify_admins_about_new_order(
            order=order,
            messenger_client=messenger_client,
            user_role_service=user_role_service,
            content_moderation=content_moderation_service,
            admin_base_url=config.admin.admin_base_url,
            currency_symbol=config.market.currency_symbol,
        )

    msg_success = await bot_texts_service.get(
        "msg_advertiser_after_payment_success", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_success,
    )
    msg_what_next = await bot_texts_service.get(
        "msg_advertiser_after_payment_what_next", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_what_next,
        parse_mode="Markdown",
    )
    after_texts = await bot_texts_service.get_many(
        ["btn_create_order", "btn_my_orders", "btn_support"],
        locale,
    )
    msg_important = await bot_texts_service.get(
        "msg_advertiser_after_payment_important", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_important,
        parse_mode="Markdown",
        keyboard=advertiser_after_payment_keyboard(after_texts),
    )
