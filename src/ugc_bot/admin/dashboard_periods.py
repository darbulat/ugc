"""Calendar windows shared by dashboard and creator directory metrics."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PeriodKey = Literal["today", "yesterday", "7d", "30d", "all"]


@dataclass(slots=True)
class PeriodWindow:
    """Time window for current and previous periods."""

    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime


def dashboard_period_window(
    period: PeriodKey | Literal["90d"], timezone: ZoneInfo
) -> PeriodWindow:
    """Build time windows for current and previous periods."""
    now = datetime.now(timezone)
    start_of_today = datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        tzinfo=timezone,
    )
    if period == "today":
        current_start = start_of_today
        current_end = now
        previous_start = start_of_today - timedelta(days=1)
        previous_end = now - timedelta(days=1)
    elif period == "yesterday":
        current_end = start_of_today
        current_start = current_end - timedelta(days=1)
        previous_end = current_start
        previous_start = previous_end - timedelta(days=1)
    elif period in ("7d", "30d", "90d"):
        days = int(period[:-1])
        current_end = now
        current_start = start_of_today - timedelta(days=days - 1)
        previous_start = current_start - timedelta(days=days)
        previous_end = now - timedelta(days=days)
    elif period == "all":
        current_start = datetime(2000, 1, 1, tzinfo=timezone)
        current_end = now
        previous_start = current_start
        previous_end = current_start
    else:
        raise ValueError(f"Unsupported period: {period}")
    return PeriodWindow(
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
    )
