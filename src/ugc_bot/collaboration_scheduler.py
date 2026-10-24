"""Deadline loop started by the combined scheduler when core is enabled."""

import asyncio
import logging

from ugc_bot.application.services.collaboration_sweep_service import (
    CollaborationSweepService,
)

logger = logging.getLogger(__name__)


async def run_loop(
    sweep: CollaborationSweepService,
    *,
    interval_seconds: int = 60,
    max_iterations: int | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("positive_sweep_interval_required")
    iteration = 0
    while True:
        iteration += 1
        try:
            result = await sweep.run_once()
            logger.info(
                "Collaboration deadlines checked",
                extra={
                    "attempted": result.attempted,
                    "changed": result.changed,
                    "rejected": result.rejected,
                },
            )
        except Exception:
            logger.exception("Collaboration deadline sweep failed")
        if max_iterations is not None and iteration >= max_iterations:
            return
        await asyncio.sleep(interval_seconds)
