"""Remove abandoned JPEG uploads daily; bound order images are retained."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_loop(service, *, interval_seconds=86400, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("order_image_cleanup_loop_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            await service.cleanup()
        except Exception as exc:
            logger.error(
                "Order image cleanup failed",
                extra={"error_type": type(exc).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)


async def run_enabled(
    config, container, bot, *, interval_seconds=86400, max_iterations=None
):
    service = container.build_order_image_service()
    if service is not None:
        await run_loop(
            service,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations,
        )
