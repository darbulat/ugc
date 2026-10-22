"""Pure integer v1 arithmetic. Legacy commission functions remain unchanged."""

from datetime import datetime, timezone
from typing import Literal

MAX_MINOR = 2**63 - 1


def utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("aware_timestamp_required")
    return value.astimezone(timezone.utc)


def first_anniversary(registered_at: datetime) -> datetime:
    registered_at = utc(registered_at)
    try:
        return registered_at.replace(year=registered_at.year + 1)
    except ValueError:
        return registered_at.replace(year=registered_at.year + 1, day=28)


def commission_minor(base_minor: int, rate: int, currency: str) -> int:
    if currency != "RUB":
        raise ValueError("unpublished_currency")
    if type(base_minor) is not int or not 0 <= base_minor <= MAX_MINOR:
        raise ValueError("invalid_minor_amount")
    if type(rate) is not int or not 0 <= rate <= 10000:
        raise ValueError("invalid_rate_bps")
    return (base_minor * rate + 5000) // 10000


def rate_bps(
    referred_registered_at: datetime,
    snapshot_at: datetime,
    *,
    side: Literal["client", "creator"],
    verified_count: int = 0,
) -> int:
    registered, snapshot = utc(referred_registered_at), utc(snapshot_at)
    if snapshot < registered:
        raise ValueError("snapshot_before_registration")
    if side not in ("client", "creator"):
        raise ValueError("invalid_referral_side")
    if type(verified_count) is not int or verified_count < 0:
        raise ValueError("invalid_verified_count")
    if snapshot >= first_anniversary(registered):
        return 300
    if side == "client":
        return 1000
    return next(
        rate
        for threshold, rate in (
            (400, 2000),
            (200, 1500),
            (100, 1200),
            (0, 1000),
        )
        if verified_count >= threshold
    )
