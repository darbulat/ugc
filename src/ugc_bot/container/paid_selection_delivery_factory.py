"""Paid contact receipts use dedicated durable facts and one-shot transports."""

from typing import TYPE_CHECKING

from ugc_bot.application.notice_delivery_ports import NoticeReceiptTransport
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.paid_selection_delivery import (
    SqlAlchemyPaidSelectionDeliveryRepository,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    RoutedNoticeReceipts,
    TelegramNoticeReceipts,
)

if TYPE_CHECKING:
    from aiogram import Bot
    from aiohttp import ClientSession


def build_paid_selection_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    bot: "Bot",
    *,
    max_session: "ClientSession | None" = None,
) -> PaidSelectionDelivery | None:
    if not config.financial.core_enabled:
        return None
    transports: dict[str, NoticeReceiptTransport] = {
        "telegram": TelegramNoticeReceipts(bot)
    }
    if (
        config.max_bot
        and config.max_bot.token.strip()
        and max_session is not None
    ):
        transports["max"] = MaxNoticeReceipts(max_session, config.max_bot.token)
    return PaidSelectionDelivery(
        SqlAlchemyPaidSelectionDeliveryRepository(),
        transactions,
        RoutedNoticeReceipts(transports),
        SystemClock(),
    )
