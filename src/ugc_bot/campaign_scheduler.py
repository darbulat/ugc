"""Run an explicitly enabled campaign worker."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_loop(worker, *, interval_seconds=5, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("campaign_worker_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            await worker.run_once()
        except Exception as error:
            logger.error(
                "Campaign worker cycle failed",
                extra={"error_type": type(error).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)
