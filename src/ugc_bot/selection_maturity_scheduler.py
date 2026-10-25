"""Periodic selection maturity uses authoritative stored schedules."""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_loop(sweep, *, interval_seconds=60, max_iterations=None):
    if interval_seconds <= 0 or (
        max_iterations is not None and max_iterations < 1
    ):
        raise ValueError("selection_sweep_bounds_invalid")
    iteration = 0
    while True:
        iteration += 1
        try:
            result = await sweep.run_once()
            logger.info(
                "Selection maturity checked",
                extra=dict(
                    attempted=result.attempted,
                    closed=result.closed,
                    deferred=result.deferred,
                ),
            )
        except Exception as error:
            logger.error(
                "Selection maturity sweep failed",
                extra={"error_type": type(error).__name__},
            )
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)
