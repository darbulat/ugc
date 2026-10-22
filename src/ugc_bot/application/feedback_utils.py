"""Shared utilities for feedback scheduling."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def needs_feedback_reminder(feedback_text: str | None) -> bool:
    """Return True if feedback reminder needed (no final response yet).

    Users who chose postpone ("⏳ Ещё не связался") get reminders again.
    """
    if feedback_text is None:
        return True
    if feedback_text.lstrip().startswith(("✅", "❌", "⚠")):
        return False
    lower = feedback_text.lower()
    return (
        "ещё не связался" in lower
        or "еще не связался" in lower
        or "⏳" in feedback_text
    )


def next_reminder_datetime(
    reminder_timezone: str = "Europe/Moscow",
    reminder_hour: int = 10,
    reminder_minute: int = 0,
) -> datetime:
    """Return next reminder time: tomorrow at configured hour in timezone (UTC).

    Ensures reminders are sent every 24h at the configured time (e.g. 10:00).
    """
    tz = ZoneInfo(reminder_timezone)
    now_local = datetime.now(tz)
    tomorrow = now_local.date() + timedelta(days=1)
    next_local = datetime(
        tomorrow.year,
        tomorrow.month,
        tomorrow.day,
        hour=reminder_hour,
        minute=reminder_minute,
        second=0,
        microsecond=0,
        tzinfo=tz,
    )
    return next_local.astimezone(timezone.utc)
