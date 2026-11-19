"""Deliver queued profile notices; never fetch Instagram or generate codes."""

import asyncio
import logging
from contextlib import AsyncExitStack

import aiohttp

from ugc_bot.application.services.instagram_profile_maintenance import (
    InstagramProfileNoticeDelivery,
)
from ugc_bot.container.instagram_maintenance_factory import (
    build_profile_maintenance,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    RoutedNoticeReceipts,
    TelegramNoticeReceipts,
)

logger = logging.getLogger(__name__)


async def run_enabled(config, container, bot, *, max_iterations=None):
    maintenance = build_profile_maintenance(
        config, container.build_repos(), container.transaction_manager
    )
    if maintenance is None:
        return
    async with AsyncExitStack() as resources:
        transports = {"telegram": TelegramNoticeReceipts(bot)}
        if config.max_bot and config.max_bot.token.strip():
            session = await resources.enter_async_context(
                aiohttp.ClientSession()
            )
            transports["max"] = MaxNoticeReceipts(session, config.max_bot.token)
        worker = InstagramProfileNoticeDelivery(
            maintenance.repo,
            maintenance.transactions,
            RoutedNoticeReceipts(transports),
            SystemClock(),
        )
        iteration = 0
        while True:
            iteration += 1
            try:
                await worker.run_once()
            except Exception as exc:
                logger.error(
                    "Instagram notice batch failed",
                    extra={"error_type": type(exc).__name__},
                )
            if max_iterations is not None and iteration >= max_iterations:
                return
            await asyncio.sleep(60)
