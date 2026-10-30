"""Deliver durable order notices independently of new-sales feature gates."""

import asyncio
import logging

from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)

logger = logging.getLogger(__name__)


async def run_loop(worker, *, interval_seconds=5, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("order_notice_loop_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            # Drain a bounded batch per pass while permitting graceful cancel.
            for _ in range(100):
                if not await worker.run_once():
                    break
        except Exception as exc:
            logger.error(
                "Order notice batch failed",
                extra={"error_type": type(exc).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)


async def run_enabled(
    config, container, bot, *, interval_seconds=5, max_iterations=None
):
    # The durable queue records uncertain delivery. Retrying inside the
    # adapter could duplicate a message that Telegram accepted before a
    # network error reached us.
    worker = container.build_order_notice_delivery(
        TelegramMessengerClient(bot, retry_attempts=1)
    )
    if worker is not None:
        await run_loop(
            worker,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations,
        )
