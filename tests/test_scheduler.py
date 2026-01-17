"""Tests for scheduler stub."""

from __future__ import annotations

from ugc_bot.scheduler.scheduler import Scheduler


def test_scheduler_start_stop() -> None:
    """Ensure scheduler start/stop are callable."""

    scheduler = Scheduler()
    assert scheduler.start() is None
    assert scheduler.shutdown() is None
