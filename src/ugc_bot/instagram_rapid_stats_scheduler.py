"""Scheduler: Instagram stats via Rapid API -> instagram_stats table."""

import asyncio
import logging

from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


async def run_once(service) -> None:
    """Run a single Rapid API Instagram stats collection cycle."""
    logger.debug("Starting Instagram Rapid API stats cycle")
    updated, errors = await service.run_once()
    logger.info(
        "Instagram Rapid API stats cycle completed",
        extra={"updated": updated, "errors": errors},
    )


async def run_loop(
    service,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic Instagram Rapid API stats collection."""
    install_asyncio_exception_handler("instagram-rapid-stats-scheduler")
    iterations = 0
    logger.info("Instagram Rapid API stats scheduler loop started")
    try:
        while True:
            iterations += 1
            await run_once(service)
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Instagram Rapid API stats scheduler loop stopped",
            extra={"total_iterations": iterations},
        )


def main() -> None:  # pragma: no cover - entry point, not unit-tested
    """Start Instagram Rapid API stats scheduler loop."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("instagram-rapid-stats-scheduler")
    log_startup_info(
        logger=logger,
        service_name="Instagram Rapid API stats scheduler",
        config=config,
    )

    if not config.instagram.instagram_rapid_stats_enabled:
        logger.info("Instagram Rapid API stats scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error(
            "DATABASE_URL is required for Instagram Rapid API stats scheduler"
        )
        return

    ig = config.instagram
    if not ig.rapidapi_key or not ig.rapidapi_instagram_host:
        logger.error(
            "RAPIDAPI_KEY and RAPIDAPI_INSTAGRAM_HOST are required for "
            "Instagram Rapid API stats scheduler"
        )
        return

    logger.info(
        "Initializing Instagram Rapid API stats scheduler",
        extra={
            "interval_seconds": ig.instagram_rapid_stats_interval_seconds,
            "batch_size": ig.instagram_rapid_stats_batch_size,
        },
    )
    container = Container(config)
    deps = container.build_instagram_rapid_stats_scheduler_deps()
    service = deps["instagram_rapid_stats_collector_service"]
    interval = deps["interval_seconds"]

    asyncio.run(
        run_loop(
            service,
            interval_seconds=interval,
        )
    )


if __name__ == "__main__":
    main()  # pragma: no cover
