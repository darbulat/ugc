"""A lead-only delivery owner uses existing receipt-aware transports."""

from typing import TYPE_CHECKING

from ugc_bot.application.notice_delivery_ports import NoticeReceiptTransport
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.accompaniment_lead_delivery import (
    AccompanimentLeadDelivery,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.accompaniment_lead_delivery import (
    SqlAlchemyAccompanimentLeadDeliveryRepository,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    RoutedNoticeReceipts,
    TelegramNoticeReceipts,
)

if TYPE_CHECKING:
    from aiogram import Bot
    from aiohttp import ClientSession


def build_lead_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    bot: "Bot",
    *,
    max_session: "ClientSession | None" = None,
) -> AccompanimentLeadDelivery:
    transports: dict[str, NoticeReceiptTransport] = {
        "telegram": TelegramNoticeReceipts(bot)
    }
    max_config = config.max_bot
    if max_config and max_config.token.strip() and max_session is not None:
        transports["max"] = MaxNoticeReceipts(max_session, max_config.token)
    recipients = config.admin.business_order_telegram_recipients
    browser_recipients = config.admin.browser_paid_order_telegram_recipients
    # A browser payment can narrow access to a delayed created card.
    if browser_recipients is not None:
        recipients = recipients.intersection(browser_recipients)
    return AccompanimentLeadDelivery(
        SqlAlchemyAccompanimentLeadDeliveryRepository(recipients),
        transactions,
        RoutedNoticeReceipts(transports),
        SystemClock(),
    )
