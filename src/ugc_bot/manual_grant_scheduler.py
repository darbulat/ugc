"""Mature approved grants after independent hold and funding checks."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_loop(sweep, *, interval_seconds=60, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("manual_grant_sweep_bounds_invalid")
    iterations = 0
    while True:
        iterations += 1
        try:
            await sweep.run_once()
        except Exception as error:
            logger.error(
                "Manual grant maturity failed",
                extra={"error_type": type(error).__name__},
            )
        if max_iterations is not None and iterations >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)
