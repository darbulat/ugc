"""Default-off notice runtime; owns optional MAX HTTP resources, no DB locks."""

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

import aiohttp

from ugc_bot.application.services.collaboration_notice_delivery import (
    CollaborationNoticeDelivery,
)

if TYPE_CHECKING:
    from aiogram import Bot

    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container

logger = logging.getLogger(__name__)


async def run_loop(
    worker: CollaborationNoticeDelivery,
    *,
    interval_seconds: int = 60,
    max_iterations: int | None = None,
) -> None:
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("notice_loop_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            attempted = await worker.run_once()
            logger.info(
                "Collaboration notice events checked",
                extra={"attempted": attempted},
            )
        except Exception as exc:
            # Provider bodies, tokens, contact snapshots and SQL parameter
            # payloads are not safe scheduler log fields.
            logger.error(
                "Collaboration notice batch failed",
                extra={"error_type": type(exc).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)


async def run_enabled(
    config: "AppConfig",
    container: "Container",
    bot: "Bot",
    *,
    interval_seconds: int = 60,
    max_iterations: int | None = None,
) -> None:
    if not getattr(getattr(config, "financial", None), "core_enabled", False):
        return
    async with AsyncExitStack() as resources:
        max_config = getattr(config, "max_bot", None)
        max_session: aiohttp.ClientSession | None = None
        if max_config and max_config.token.strip():
            max_session = await resources.enter_async_context(
                aiohttp.ClientSession()
            )
        worker = container.build_collaboration_notice_delivery(
            bot, max_session=max_session
        )
        if worker is not None:
            await run_loop(
                worker,
                interval_seconds=interval_seconds,
                max_iterations=max_iterations,
            )
