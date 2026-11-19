"""Profile checks are evidence of availability, never proof of ownership."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
FAILURE_SPACING = timedelta(hours=6)
REFRESH_CALLBACK = "instagram:refresh"


def next_profile_notice_at(at: datetime) -> datetime:
    """08:00 inclusive, 21:00 exclusive, even after a deferred retry."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("profile_notice_time_must_be_aware")
    local = at.astimezone(MOSCOW)
    if 8 <= local.hour < 21:
        return at
    morning = local.replace(hour=8, minute=0, second=0, microsecond=0)
    return morning if local.hour < 8 else morning + timedelta(days=1)


def next_failure_count(
    count: int, last_failure: datetime | None, at: datetime
) -> int:
    if last_failure is None or at - last_failure >= FAILURE_SPACING:
        return count + 1
    return count
