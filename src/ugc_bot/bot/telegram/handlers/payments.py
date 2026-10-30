"""Telegram payment handlers."""

import asyncio
import logging
from typing import cast
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
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
    notify_admins_about_order_paid,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
    native_receipt,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.payment_service import (
    InvoiceData,
    PaymentService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.checkout import send_checkout_if_v1
from ugc_bot.bot.telegram.handlers.keyboards import (
    PAY_ORDER_CALLBACK_PREFIX,
    advertiser_menu_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)

router = Router()
logger = logging.getLogger(__name__)


async def send_order_invoice(
    incoming_message,
    messenger_client: MessengerClient,
    order_id: UUID,
    offer_text: str,
    invoice_data: InvoiceData,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
) -> None:
    """Send invoice using pre-calculated InvoiceData."""
    locale = user_locale

    if not incoming_message.chat_id:
        return

    price = int(invoice_data.total * 100)
    if price > 100_000_000:
        msg_too_large = await bot_texts_service.get(
            "msg_order_amount_too_large", locale
        )
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id,
            text=msg_too_large,
        )
        return

    try:
        total_display = (
            int(invoice_data.total)
            if invoice_data.total == int(invoice_data.total)
            else invoice_data.total
        )
        label = f"💳 {total_display} {invoice_data.currency_symbol}"
        amount_str = f"{total_display} {invoice_data.currency_symbol}"
        pay_btn_template = await bot_texts_service.get(
            "btn_pay_invoice", locale
        )
        pay_button_text = pay_btn_template.format(amount=amount_str)
        await messenger_client.send_invoice(
            chat_id=incoming_message.chat_id,
            invoice=Invoice(
                title=await bot_texts_service.get("msg_title_payment", locale),
                description=offer_text[:255],
                payload=str(order_id),
                provider_token=invoice_data.provider_token,
                currency=invoice_data.currency,
                items=[InvoiceItem(label=label, amount_minor=price)],
                provider_data=invoice_data.provider_data,
                need_email=invoice_data.need_email,
                send_email_to_provider=invoice_data.need_email,
                pay_button_text=pay_button_text,
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


def _parse_pay_order_id_from_start(text: str) -> UUID | None:
    """Parse order id from /start pay_<order_id>. Return None if invalid."""
    if not text or " pay_" not in text:
        return None
    parts = text.split(" ", 1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("pay_"):
        return None
    try:
        return UUID(payload[4:])
    except (ValueError, TypeError):
        return None


@router.message(
    CommandStart(),
    F.text.startswith("/start pay_"),
)
async def start_pay_order_link(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    payment_service: PaymentService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    checkout_service=None,
) -> None:
    """Handle t.me/bot?start=pay_ORDER_ID — send invoice for that order."""
    order_id = _parse_pay_order_id_from_start(message.text or "")
    if order_id is None:
        return
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_payment_blocked",
            "msg_payment_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_payment_blocked", ""),
        pause_msg=allow_msgs.get("msg_payment_pause", ""),
    )
    if user is None:
        return
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
    if await send_checkout_if_v1(
        order_id,
        user,
        incoming,
        message,
        messenger_client,
        payment_service,
        checkout_service,
        config,
        locale,
    ):
        return
    result = await payment_service.validate_order_for_invoice(
        order_id, user.user_id, user.country, config
    )
    if isinstance(result, str):
        msg = await bot_texts_service.get(result, locale)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)
        return
    order, invoice_data = result
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        invoice_data=invoice_data,
        bot_texts_service=bot_texts_service,
        user_locale=user_locale,
    )


@router.message(Command("pay_order"))
async def pay_order(
    message: Message,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    payment_service: PaymentService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    checkout_service=None,
) -> None:
    """Send Telegram invoice for an order (email via payment form)."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_payment_blocked",
            "msg_payment_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_payment_blocked", ""),
        pause_msg=allow_msgs.get("msg_payment_pause", ""),
    )
    if user is None:
        return

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

    if await send_checkout_if_v1(
        order_id,
        user,
        incoming,
        message,
        messenger_client,
        payment_service,
        checkout_service,
        config,
        locale,
    ):
        return
    result = await payment_service.validate_order_for_invoice(
        order_id, user.user_id, user.country, config
    )
    if isinstance(result, str):
        msg = await bot_texts_service.get(result, locale)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)
        return
    order, invoice_data = result
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        invoice_data=invoice_data,
        bot_texts_service=bot_texts_service,
        user_locale=user_locale,
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
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    checkout_service=None,
) -> None:
    """Send Telegram invoice for an order from 'My orders' list button."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_payment_blocked",
            "msg_payment_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_payment_blocked", ""),
        pause_msg=allow_msgs.get("msg_payment_pause", ""),
    )
    if user is None:
        return

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

    if await send_checkout_if_v1(
        order_id,
        user,
        incoming,
        callback,
        messenger_client,
        payment_service,
        checkout_service,
        config,
        locale,
    ):
        return
    result = await payment_service.validate_order_for_invoice(
        order_id, user.user_id, user.country, config
    )
    if isinstance(result, str):
        msg = await bot_texts_service.get(result, locale)
        await messenger_client.send_text(chat_id=incoming.chat_id, text=msg)
        return
    order, invoice_data = result
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        invoice_data=invoice_data,
        bot_texts_service=bot_texts_service,
        user_locale=user_locale,
    )


@router.pre_checkout_query()
async def pre_checkout_query_handler(
    pre_checkout_query: PreCheckoutQuery,
    payment_provider: PaymentProvider,
    event_adapter: MessengerEventAdapter | None = None,
    payment_service: PaymentService | None = None,
    checkout_service=None,
) -> None:
    """Confirm pre-checkout query from Telegram."""
    adapter = cast(
        MessengerEventAdapter,
        event_adapter if event_adapter is not None else TelegramEventAdapter(),
    )
    incoming = adapter.from_pre_checkout(pre_checkout_query)
    if payment_service is not None or checkout_service is not None:
        try:
            async with asyncio.timeout(7):
                order_id = UUID(incoming.payload)
                order = (
                    await payment_service.get_order(order_id)
                    if payment_service
                    else None
                )
                if order is None:
                    raise ValueError("order_not_found")
                if order.financial_version is not None:
                    if checkout_service is None:
                        raise ValueError("checkout_unavailable")
                    await checkout_service.authorize(
                        order_id,
                        incoming.user.external_id,
                        incoming.query_id,
                        incoming.total_amount,
                        incoming.currency,
                    )
        except Exception:
            await payment_provider.reject_pre_checkout(
                query_id=incoming.query_id,
                error_message=(
                    "Оплата пока недоступна. Проверьте сохранённый статус "
                    "заказа."
                ),
            )
            return
    await payment_provider.confirm_pre_checkout(query_id=incoming.query_id)


async def _persist_native_paid(incoming, checkout_service, payment_service):
    if checkout_service is None:
        return False
    processor = PaidReceiptProcessor(
        checkout_service.repository,
        checkout_service.transactions,
        payment_service,
    )
    try:
        receipt = native_receipt(incoming)
    except ValueError:
        return False
    return await processor.accept(receipt)


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
    user_role_service: UserRoleService,
    payment_service: PaymentService,
    content_moderation_service: ContentModerationService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    checkout_service=None,
) -> None:
    """Handle successful Telegram payment."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    if incoming.successful_payment is None:
        return
    if await _persist_native_paid(incoming, checkout_service, payment_service):
        return

    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_payment_blocked",
            "msg_payment_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_payment_blocked", ""),
        pause_msg=allow_msgs.get("msg_payment_pause", ""),
    )
    if user is None:
        return

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
            receipt=incoming.successful_payment,
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
    if order and getattr(payment_service, "order_notices", None) is None:
        invoice_data = (
            await payment_service.calculate_invoice_data(
                order, user.country, config
            )
            if order.financial_version is None
            else None
        )
        symbol = (
            invoice_data.currency_symbol
            if invoice_data
            else config.market.currency_symbol
        )
        await notify_admins_about_order_paid(
            order=order,
            messenger_client=messenger_client,
            user_role_service=user_role_service,
            content_moderation=content_moderation_service,
            admin_base_url=config.admin.admin_base_url,
            currency_symbol=symbol,
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
        [
            "btn_create_order",
            "btn_my_orders",
            "btn_rate_creators",
            "btn_my_profile",
            "btn_edit_profile",
            "btn_partner_program",
        ],
        locale,
    )
    msg_important = await bot_texts_service.get(
        "msg_advertiser_after_payment_important", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_important,
        parse_mode="Markdown",
        keyboard=advertiser_menu_inline_keyboard(after_texts),
    )
