"""Scheduler for periodic Instagram profile stats update."""

import asyncio
import logging

import aiohttp
from aiogram import Bot

from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.max.client import MaxMessengerClient
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


async def run_once(service) -> None:
    """Run a single Instagram stats update cycle."""
    logger.debug("Starting Instagram stats update cycle")
    updated, errors = await service.run_once()
    logger.info(
        "Instagram stats update cycle completed",
        extra={"updated": updated, "errors": errors},
    )


async def run_loop(
    service,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic Instagram stats update."""
    install_asyncio_exception_handler("instagram-stats-scheduler")
    iterations = 0
    logger.info("Instagram stats scheduler loop started")
    try:
        while True:
            iterations += 1
            await run_once(service)
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Instagram stats scheduler loop stopped",
            extra={"total_iterations": iterations},
        )


def main() -> None:  # pragma: no cover - entry point, not unit-tested
    """Start Instagram stats update scheduler loop."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("instagram-stats-scheduler")
    log_startup_info(
        logger=logger,
        service_name="Instagram stats scheduler",
        config=config,
    )

    if not config.instagram.instagram_stats_update_enabled:
        logger.info("Instagram stats scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for Instagram stats scheduler")
        return

    ig = config.instagram
    logger.info(
        "Initializing Instagram stats scheduler",
        extra={
            "interval_seconds": ig.instagram_stats_update_interval_seconds,
            "batch_size": ig.instagram_stats_batch_size,
        },
    )
    container = Container(config)
    bot_texts_service = container.build_bot_texts_service()
    bot = Bot(token=config.bot.bot_token)
    telegram_messenger_client = TelegramMessengerClient(bot)

    if not (config.max_bot is not None and config.max_bot.token):
        logger.info(
            "MAX_BOT token not configured; "
            "Instagram-loss notifications via Max disabled"
        )

    async def _run() -> None:
        # aiohttp.ClientSession() must be created inside a running event loop.
        max_session: aiohttp.ClientSession | None = None
        max_messenger_client: MaxMessengerClient | None = None
        if config.max_bot is not None and config.max_bot.token:
            max_session = aiohttp.ClientSession()
            max_messenger_client = MaxMessengerClient(
                token=config.max_bot.token, session=max_session
            )

        deps = container.build_instagram_stats_scheduler_deps(
            telegram_messenger_client=telegram_messenger_client,
            max_messenger_client=max_messenger_client,
            bot_texts_service=bot_texts_service,
        )
        service = deps["instagram_stats_update_service"]
        interval = deps["interval_seconds"]

        try:
            await run_loop(service, interval_seconds=interval)
        finally:
            tg_session = getattr(bot, "session", None)
            if tg_session is not None:
                await tg_session.close()
            if max_session is not None:
                await max_session.close()
            await container.dispose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()  # pragma: no cover
