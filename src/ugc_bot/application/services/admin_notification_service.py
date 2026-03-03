"""Service for notifying admins about new complaints and orders via Telegram."""

import html
import logging
from typing import Any

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Complaint, Order
from ugc_bot.domain.enums import MessengerType, OrderType

logger = logging.getLogger(__name__)

MOD_ACTIVATE_CALLBACK_PREFIX = "mod_activate:"


async def _send_admin_text(
    messenger_client: Any,
    *,
    chat_id: str,
    text: str,
    keyboard: Keyboard | None = None,
    parse_mode: str | None = None,
) -> None:
    """Send text using messenger client or raw bot."""
    if hasattr(messenger_client, "send_text"):
        await messenger_client.send_text(
            chat_id=chat_id, text=text, keyboard=keyboard, parse_mode=parse_mode
        )
        return
    if hasattr(messenger_client, "send_message"):
        await messenger_client.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=keyboard,
            parse_mode=parse_mode,
        )
        return
    raise AttributeError("Messenger client lacks send methods")


async def _send_admin_photo(
    messenger_client: Any,
    *,
    chat_id: str,
    file_id: str,
    caption: str | None,
    keyboard: Keyboard | None = None,
    parse_mode: str | None = None,
) -> None:
    """Send photo using messenger client or raw bot."""
    if hasattr(messenger_client, "send_text"):
        await messenger_client.send_photo(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            parse_mode=parse_mode,
            keyboard=keyboard,
        )
        return
    if hasattr(messenger_client, "send_photo"):
        await messenger_client.send_photo(
            chat_id=int(chat_id),
            photo=file_id,
            caption=caption,
            reply_markup=keyboard,
            parse_mode=parse_mode,
        )
        return
    raise AttributeError("Messenger client lacks send_photo")


def _format_order_type_for_moderation(order: Order) -> str:
    """Format order type for admin moderation message."""
    if order.order_type == OrderType.UGC_PLUS_PLACEMENT:
        return "UGC + размещение"
    return "UGC-видео для бренда"


def _format_optional_field(value: str | None) -> str:
    """Return value or em dash if empty."""
    return value.strip() if value and value.strip() else "—"


async def notify_admins_about_complaint(
    complaint: Complaint,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
) -> None:
    """Send complaint details to all Telegram admins.

    Args:
        complaint: The created complaint.
        messenger_client: Messenger client for sending messages.
        user_role_service: Service to fetch admin list and usernames.
    """
    admins = await user_role_service.list_admins(
        messenger_type=MessengerType.TELEGRAM
    )
    if not admins:
        logger.debug("No Telegram admins to notify about complaint")
        return

    reporter = await user_role_service.get_user_by_id(complaint.reporter_id)
    reported = await user_role_service.get_user_by_id(complaint.reported_id)
    reporter_name = (
        reporter.username if reporter else str(complaint.reporter_id)
    )
    reported_name = (
        reported.username if reported else str(complaint.reported_id)
    )

    text = (
        "🔔 *Новая жалоба*\n\n"
        f"*ID жалобы:* `{complaint.complaint_id}`\n"
        f"*Жалобу подал:* {reporter_name}\n"
        f"*На пользователя:* {reported_name}\n"
        f"*Заказ:* `{complaint.order_id}`\n"
        f"*Причина:* {complaint.reason}"
    )
    if complaint.file_ids:
        text += f"\n*Фото:* {len(complaint.file_ids)} шт."

    for admin in admins:
        try:
            chat_id = admin.external_id
            if complaint.file_ids:
                await _send_admin_photo(
                    messenger_client,
                    chat_id=chat_id,
                    file_id=complaint.file_ids[0],
                    caption=text,
                    parse_mode="Markdown",
                )
                for file_id in complaint.file_ids[1:]:
                    await _send_admin_photo(
                        messenger_client,
                        chat_id=chat_id,
                        file_id=file_id,
                        caption=None,
                    )
            else:
                await _send_admin_text(
                    messenger_client,
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
        except Exception as exc:
            logger.warning(
                "Failed to notify admin about complaint",
                extra={
                    "admin_id": str(admin.user_id),
                    "complaint_id": str(complaint.complaint_id),
                    "error": str(exc),
                },
            )


async def notify_admins_about_new_order(
    order: Order,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    content_moderation: ContentModerationService,
    admin_base_url: str = "",
    currency_symbol: str = "₽",
) -> None:
    """Send order details to all Telegram admins for moderation.

    Args:
        order: The order pending moderation.
        messenger_client: Messenger client for sending messages.
        user_role_service: Service to fetch admin list and usernames.
        content_moderation: Service to check for banned content.
        admin_base_url: Optional base URL for admin panel links.
        currency_symbol: Symbol for price display (e.g. ₽, $).
    """
    admins = await user_role_service.list_admins(
        messenger_type=MessengerType.TELEGRAM
    )
    if not admins:
        logger.debug("No Telegram admins to notify about new order")
        return

    advertiser = await user_role_service.get_user_by_id(order.advertiser_id)
    advertiser_name = (
        advertiser.username if advertiser else str(order.advertiser_id)
    )

    banned_warning = ""
    if content_moderation.order_contains_banned_content(
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=order.barter_description,
        content_usage=order.content_usage,
        geography=order.geography,
    ):
        banned_warning = "\n\n⚠️ <b>Обнаружен возможный запрещённый контент</b>"

    order_id_hex = order.order_id.hex
    buttons: list[list[Button]] = []
    if admin_base_url and admin_base_url.rstrip("/"):
        base = admin_base_url.rstrip("/")
        link_url = f"{base}/order-model/edit/{order.order_id}"
        buttons.append([Button(text="Открыть в админке", url=link_url)])
    buttons.append(
        [
            Button(
                text="Активировать",
                callback_data=f"{MOD_ACTIVATE_CALLBACK_PREFIX}{order_id_hex}",
            )
        ]
    )
    reply_markup = Keyboard(kind=KeyboardKind.INLINE, rows=buttons)

    advertiser_esc = html.escape(advertiser_name)
    offer_esc = html.escape(order.offer_text or "")
    product_link_esc = html.escape(order.product_link)
    order_id_esc = html.escape(str(order.order_id))
    barter_esc = html.escape(_format_optional_field(order.barter_description))
    content_usage_esc = html.escape(_format_optional_field(order.content_usage))
    deadlines_esc = html.escape(_format_optional_field(order.deadlines))
    geography_esc = html.escape(_format_optional_field(order.geography))
    order_type_esc = html.escape(_format_order_type_for_moderation(order))

    text = (
        "📋 <b>Новый заказ на модерацию</b>\n\n"
        f"<b>ID заказа:</b> <code>{order_id_esc}</code>\n"
        f"<b>Заказчик:</b> {advertiser_esc}\n"
        f"<b>Тип заказа:</b> {order_type_esc}\n"
        f"<b>Задача:</b> {offer_esc}\n"
        f"<b>Ссылка на продукт:</b> {product_link_esc}\n"
        f"<b>Бартер:</b> {barter_esc}\n"
        f"<b>Бюджет:</b> {order.price} {currency_symbol}\n"
        f"<b>Нужно креаторов:</b> {order.bloggers_needed}\n"
        f"<b>Использование контента:</b> {content_usage_esc}\n"
        f"<b>Сроки:</b> {deadlines_esc}\n"
        f"<b>География:</b> {geography_esc}"
        f"{banned_warning}"
    )

    for admin in admins:
        try:
            chat_id = admin.external_id
            if order.product_photo_file_id:
                await _send_admin_photo(
                    messenger_client,
                    chat_id=chat_id,
                    file_id=order.product_photo_file_id,
                    caption=text,
                    parse_mode="HTML",
                    keyboard=reply_markup,
                )
            else:
                await _send_admin_text(
                    messenger_client,
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    keyboard=reply_markup,
                )
        except Exception as exc:
            logger.warning(
                "Failed to notify admin about new order",
                extra={
                    "admin_id": str(admin.user_id),
                    "order_id": str(order.order_id),
                    "error": str(exc),
                },
            )
