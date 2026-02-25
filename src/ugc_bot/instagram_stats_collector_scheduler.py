"""Scheduler: Instagram stats via ScrapeCreators -> instagram_stats table."""

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
    """Run a single Instagram stats collection cycle (ScrapeCreators)."""
    logger.debug("Starting Instagram stats cycle")
    result = await service.run_once()
    logger.info(
        "Instagram stats cycle completed",
        extra={
            "updated": result.updated,
            "errors": result.errors,
            "updated_users": result.updated_users,
            "failed_users": result.failed_users,
        },
    )
    if result.updated_users:
        logger.info(
            "Updated Instagram stats for users: %s",
            [u["username"] or u["user_id"] for u in result.updated_users],
            extra={"updated_users": result.updated_users},
        )
    if result.failed_users:
        logger.warning(
            "Instagram stats update had problems for %d users: %s",
            len(result.failed_users),
            [
                (u.get("username") or u.get("user_id"), u.get("reason", "?"))
                for u in result.failed_users
            ],
            extra={"failed_users": result.failed_users},
        )


async def run_loop(
    service,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic Instagram stats collection via ScrapeCreators."""
    install_asyncio_exception_handler("instagram-stats-collector-scheduler")
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
    """Start Instagram stats scheduler loop (ScrapeCreators)."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("instagram-stats-collector-scheduler")
    log_startup_info(
        logger=logger,
        service_name="Instagram stats scheduler",
        config=config,
    )

    if not config.instagram.instagram_stats_collector_enabled:
        logger.info("Instagram stats scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for Instagram stats scheduler")
        return

    ig = config.instagram
    if not (ig.scrapecreators_api_key or "").strip():
        logger.error(
            "SCRAPECREATORS_API_KEY is required for Instagram stats scheduler"
        )
        return

    logger.info(
        "Initializing Instagram stats scheduler (ScrapeCreators)",
        extra={
            "interval_seconds": ig.instagram_stats_collector_interval_seconds,
            "batch_size": ig.instagram_stats_collector_batch_size,
        },
    )
    container = Container(config)
    deps = container.build_instagram_stats_collector_scheduler_deps()
    service = deps["instagram_stats_collector_service"]
    interval = deps["interval_seconds"]

    asyncio.run(
        run_loop(
            service,
            interval_seconds=interval,
        )
    )


if __name__ == "__main__":
    main()  # pragma: no cover
