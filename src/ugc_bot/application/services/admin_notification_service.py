"""Service for notifying admins about new complaints and orders via Telegram."""

import html
import logging
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Complaint, Order
from ugc_bot.domain.enums import MessengerType

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)


async def notify_admins_about_complaint(
    complaint: Complaint,
    bot: "Bot",
    user_role_service: UserRoleService,
) -> None:
    """Send complaint details to all Telegram admins.

    Args:
        complaint: The created complaint.
        bot: Telegram Bot instance for sending messages.
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
            chat_id = int(admin.external_id)
            if complaint.file_ids:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=complaint.file_ids[0],
                    caption=text,
                    parse_mode="Markdown",
                )
                for file_id in complaint.file_ids[1:]:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=file_id,
                    )
            else:
                await bot.send_message(
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
    bot: "Bot",
    user_role_service: UserRoleService,
    content_moderation: ContentModerationService,
    admin_base_url: str = "",
) -> None:
    """Send order details to all Telegram admins for moderation.

    Args:
        order: The order pending moderation.
        bot: Telegram Bot instance for sending messages.
        user_role_service: Service to fetch admin list and usernames.
        content_moderation: Service to check for banned content.
        admin_base_url: Optional base URL for admin panel links.
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

    offer_preview = (
        (order.offer_text[:200] + "...")
        if order.offer_text and len(order.offer_text) > 200
        else (order.offer_text or "")
    )

    banned_warning = ""
    if content_moderation.order_contains_banned_content(
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        content_usage=order.content_usage,
        geography=order.geography,
    ):
        banned_warning = "\n\n⚠️ <b>Обнаружен возможный запрещённый контент</b>"

    reply_markup = None
    if admin_base_url and admin_base_url.rstrip("/"):
        base = admin_base_url.rstrip("/")
        link_url = f"{base}/order-model/edit/{order.order_id}"
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Открыть в админке",
                        url=link_url,
                    )
                ]
            ]
        )

    advertiser_esc = html.escape(advertiser_name)
    offer_esc = html.escape(offer_preview)
    product_link_esc = html.escape(order.product_link)
    order_id_esc = html.escape(str(order.order_id))

    text = (
        "📋 <b>Новый заказ на модерацию</b>\n\n"
        f"<b>ID заказа:</b> <code>{order_id_esc}</code>\n"
        f"<b>Заказчик:</b> {advertiser_esc}\n"
        f"<b>Задача:</b> {offer_esc}\n"
        f"<b>Ссылка на продукт:</b> {product_link_esc}\n"
        f"<b>Бюджет:</b> {order.price} ₽\n"
        f"<b>Нужно креаторов:</b> {order.bloggers_needed}"
        f"{banned_warning}"
    )

    for admin in admins:
        try:
            chat_id = int(admin.external_id)
            if order.product_photo_file_id:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=order.product_photo_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
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
