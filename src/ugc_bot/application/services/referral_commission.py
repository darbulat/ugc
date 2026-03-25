"""Pure functions and dataclasses for referral commission calculation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from ugc_bot.domain.entities import Order, PayoutRequest, User
from ugc_bot.domain.enums import PayoutRequestStatus

FIRST_YEAR_RATE = 0.10
AFTER_FIRST_YEAR_RATE = 0.03


@dataclass(slots=True)
class UserReferralStats:
    """Referrer user statistics (referrals, orders, income, payouts).

    WARNING: ``income_total``, ``income_current_month`` and ``paid_total``
    sum amounts across all currencies when income entries are used.
    Use ``MultiCurrencyReferralStats`` for accurate per-currency data.
    """

    creators_count: int
    orders_count: int
    income_current_month: float
    income_total: float
    paid_total: float
    has_pending_payout: bool
    has_request_today: bool
    paid_by_currency: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class MultiCurrencyReferralStats:
    """Referral stats broken down by currency."""

    creators_count: int
    income_by_currency: dict[str, Decimal]
    orders_by_currency: dict[str, int]
    paid_by_currency: dict[str, Decimal]
    pending_by_currency: dict[str, Decimal]
    available_by_currency: dict[str, Decimal]
    has_request_today_by_currency: dict[str, bool]


def years_since(date: datetime, reference: datetime) -> float:
    """Return years between date and reference (can be fractional)."""
    delta = reference - date
    return delta.total_seconds() / (365.25 * 24 * 3600)


def get_rate(
    creator_created_at: datetime, order_completed_at: datetime
) -> float:
    """Return commission rate: 10% first year, 3% after."""
    yrs = years_since(creator_created_at, order_completed_at)
    return FIRST_YEAR_RATE if yrs < 1.0 else AFTER_FIRST_YEAR_RATE


def effective_rate(
    creator_created_at: datetime,
    order_completed_at: datetime,
    custom_rate: Optional[float],
) -> float:
    """Return rate: custom if set, else default 10%/3%."""
    if custom_rate is not None:
        return float(custom_rate)
    return get_rate(creator_created_at, order_completed_at)


def resolve_rate(
    referred_user: User, order: Order, referrer: User | None = None
) -> Decimal:
    """Return commission rate for a referral on an order.

    If the referrer has a custom ``referral_payout_rate`` it takes priority
    (the referrer earns income at their own rate).  Otherwise, the default
    10%/3% threshold based on the referrer's registration date is used.
    """
    if referrer is not None and referrer.referral_payout_rate is not None:
        return referrer.referral_payout_rate
    completed = order.completed_at or datetime.now(timezone.utc)
    base_date = (
        referrer.created_at
        if referrer is not None
        else referred_user.created_at
    )
    yrs = years_since(base_date, completed)
    return Decimal(str(FIRST_YEAR_RATE if yrs < 1.0 else AFTER_FIRST_YEAR_RATE))


def aggregate_payout_requests(
    requests: list[PayoutRequest],
    now: datetime,
) -> tuple[float, bool, bool, dict[str, float]]:
    """Return (paid_total, has_pending, has_request_today, paid_by_currency).

    WARNING: paid_total sums amounts across all currencies (deprecated).
    Use paid_by_currency for accurate per-currency breakdowns.

    has_request_today: True if ANY currency has a non-cancelled request today.
    For per-currency check use has_request_today_by_currency() repo method.
    """
    paid_total = 0.0
    paid_by_currency: dict[str, float] = {}
    has_pending = False
    has_request_today = False
    now_date = (
        now.date() if now.tzinfo else now.replace(tzinfo=timezone.utc).date()
    )
    for req in requests:
        if req.status == PayoutRequestStatus.CANCELLED:
            continue  # cancelled should not block new requests
        if req.status == PayoutRequestStatus.PENDING:
            has_pending = True
        if req.status == PayoutRequestStatus.PAID and req.amount is not None:
            amt = float(req.amount)
            paid_total += amt
            paid_by_currency[req.currency] = (
                paid_by_currency.get(req.currency, 0.0) + amt
            )
        req_date = (
            req.requested_at.date()
            if req.requested_at.tzinfo
            else req.requested_at.replace(tzinfo=timezone.utc).date()
        )
        if req_date == now_date:
            has_request_today = True
    return (paid_total, has_pending, has_request_today, paid_by_currency)
