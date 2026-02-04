"""Service for notifying admins about new complaints via Telegram."""

import logging
from typing import TYPE_CHECKING

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Complaint
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
    admins = await user_role_service.list_admins(messenger_type=MessengerType.TELEGRAM)
    if not admins:
        logger.debug("No Telegram admins to notify about complaint")
        return

    reporter = await user_role_service.get_user_by_id(complaint.reporter_id)
    reported = await user_role_service.get_user_by_id(complaint.reported_id)
    reporter_name = reporter.username if reporter else str(complaint.reporter_id)
    reported_name = reported.username if reported else str(complaint.reported_id)

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
