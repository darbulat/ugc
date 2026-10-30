"""Deliver admin requests and separately gated inactivity followups."""

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

import aiohttp

from ugc_bot.application.services.customer_workflow_delivery import (
    CustomerWorkflowDelivery,
)
from ugc_bot.container.customer_workflow_factory import (
    build_customer_workflow_delivery,
)

if TYPE_CHECKING:
    from aiogram import Bot

    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container
logger = logging.getLogger(__name__)


async def run_loop(
    worker: CustomerWorkflowDelivery,
    *,
    interval_seconds: int = 60,
    max_iterations: int | None = None,
) -> None:
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("workflow_loop_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            await worker.run_once()
        except Exception as exc:
            logger.error(
                "Customer workflow batch failed",
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
    if container is None or container.transaction_manager is None:
        return
    texts = container.build_bot_texts_service()
    await texts.load_from_db()
    async with AsyncExitStack() as resources:
        max_session = None
        if config.max_bot and config.max_bot.token.strip():
            max_session = await resources.enter_async_context(
                aiohttp.ClientSession()
            )
        worker = build_customer_workflow_delivery(
            config,
            container.transaction_manager,
            bot,
            max_session=max_session,
            texts=texts,
        )
        await run_loop(
            worker,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations,
        )
