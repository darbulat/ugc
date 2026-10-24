"""Bounded weekly summary runtime; legacy author-rating cascade is retired."""

import asyncio
import logging
from contextlib import AsyncExitStack

import aiohttp

from ugc_bot.container.campaign_digest_factory import enabled

logger = logging.getLogger(__name__)


async def run_loop(worker, *, interval_seconds=300, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("digest_loop_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            attempted = await worker.run_once()
            logger.info(
                "Campaign summary batch", extra={"attempted": attempted}
            )
        except Exception as exc:
            logger.error(
                "Campaign summary batch failed",
                extra={"error_type": type(exc).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)


async def run_enabled(config, container, bot, *, max_iterations=None):
    if not enabled(config):
        return
    async with AsyncExitStack() as resources:
        max_config = config.max_bot
        max_session = None
        if max_config and max_config.token.strip():
            max_session = await resources.enter_async_context(
                aiohttp.ClientSession()
            )
        worker = container.build_campaign_digest(bot, max_session=max_session)
        if worker is not None:
            await run_loop(
                worker,
                interval_seconds=config.feedback.feedback_poll_interval_seconds,
                max_iterations=max_iterations,
            )
