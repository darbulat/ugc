"""Durable paid receipt and notice workers independent of new-sales flags."""

import asyncio
import logging
from contextlib import suppress
from typing import cast

from ugc_bot.application.checkout_ports import (
    PaidNoticeRepository,
    PaidReceiptRepository,
)
from ugc_bot.application.services.checkout_paid_notices import (
    PaidNoticeDelivery,
)
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
)
from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

logger = logging.getLogger(__name__)


async def _work(processor, notices):
    while True:
        try:
            progressed = await processor.run_once()
            progressed = await notices.run_once() or progressed
        except Exception:
            logger.exception(
                "Checkout receipt/notice worker will recover its durable lease"
            )
            progressed = False
        await asyncio.sleep(0.1 if progressed else 2)


def start_checkout_runtime(dispatcher, bot, config):
    checkout = dispatcher.get("checkout_service")
    if not isinstance(checkout, CheckoutService):
        return None
    processor = PaidReceiptProcessor(
        cast(PaidReceiptRepository, checkout.repository),
        checkout.transactions,
        dispatcher["payment_service"],
    )
    dispatcher["checkout_paid_processor"] = processor
    if not config.bot.telegram_payment_account_id.strip():
        return None
    notices = PaidNoticeDelivery(
        cast(PaidNoticeRepository, checkout.repository),
        checkout.transactions,
        TelegramNoticeReceipts(bot),
    )
    task = asyncio.create_task(_work(processor, notices))
    dispatcher["checkout_worker_task"] = task
    return task


async def stop_checkout_runtime(dispatcher):
    task = dispatcher.get("checkout_worker_task")
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        dispatcher["checkout_worker_task"] = None


def register_checkout_lifecycle(dispatcher, config):
    async def startup(bot):
        start_checkout_runtime(dispatcher, bot, config)

    async def shutdown():
        await stop_checkout_runtime(dispatcher)

    dispatcher.startup.register(startup)
    dispatcher.shutdown.register(shutdown)
