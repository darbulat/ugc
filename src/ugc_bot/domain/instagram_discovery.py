"""Discovery is metric evidence, never Instagram ownership evidence."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
HANDLE = re.compile(r"[a-zA-Z0-9_.]{1,30}\Z")


def utc(at: datetime) -> datetime:
    return (
        at.replace(tzinfo=timezone.utc)
        if at.tzinfo is None
        else at.astimezone(timezone.utc)
    )


def next_discovery_run(at: datetime) -> datetime:
    """First/restarted workers wait for a future 10:30 Moscow slot."""
    local = utc(at).astimezone(MOSCOW)
    slot = local.replace(hour=10, minute=30, second=0, microsecond=0)
    return (slot if local < slot else slot + timedelta(days=1)).astimezone(
        timezone.utc
    )


def discovery_window(at: datetime) -> bool:
    local = utc(at).astimezone(MOSCOW)
    return (10, 30) <= (local.hour, local.minute) < (14, 0)


def freshest_count(
    *candidates: tuple[int | None, datetime | None, int],
) -> int | None:
    """Attempt timestamps must not be passed as metric observation times."""
    valid = [
        (value, utc(at) if at else None, priority)
        for value, at, priority in candidates
        if type(value) is int and value >= 0
    ]
    if not valid:
        return None
    return max(
        valid,
        key=lambda c: (
            c[1] is not None,
            c[1] or datetime.min.replace(tzinfo=timezone.utc),
            c[2],
        ),
    )[0]


@dataclass(frozen=True)
class DiscoveryTarget:
    user_id: UUID
    meta_id: str
    identity_context: str
    username: str
    profile_url: str
    attempt_id: UUID


@dataclass(frozen=True)
class DiscoveryProfile:
    object_id: str
    username: str
    followers_count: int | None = None
    media_count: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscoveryDiagnostic:
    """Allowlisted provider metadata; never error text, headers or bodies."""

    http_status: int | None = None
    meta_code: int | None = None
    meta_subcode: int | None = None
    transient: bool | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    outcome: str
    profile: DiscoveryProfile | None = None
    usage_percent: float = 0
    diagnostic: DiscoveryDiagnostic = field(default_factory=DiscoveryDiagnostic)
