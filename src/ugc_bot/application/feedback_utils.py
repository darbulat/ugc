"""Shared utilities for feedback scheduling."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ugc_bot.config import FeedbackConfig


def next_reminder_datetime(feedback_config: FeedbackConfig) -> datetime:
    """Return next reminder time: tomorrow at configured hour in timezone (UTC).

    Ensures reminders are sent every 24h at the configured time (e.g. 10:00).
    """
    tz = ZoneInfo(feedback_config.feedback_reminder_timezone)
    now_local = datetime.now(tz)
    tomorrow = now_local.date() + timedelta(days=1)
    next_local = datetime(
        tomorrow.year,
        tomorrow.month,
        tomorrow.day,
        hour=feedback_config.feedback_reminder_hour,
        minute=feedback_config.feedback_reminder_minute,
        second=0,
        microsecond=0,
        tzinfo=tz,
    )
    return next_local.astimezone(timezone.utc)
