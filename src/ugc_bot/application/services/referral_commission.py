"""Pure functions and dataclasses for referral commission calculation."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from ugc_bot.domain.entities import Order, PayoutRequest, User
from ugc_bot.domain.enums import PayoutRequestStatus

FIRST_YEAR_RATE = 0.10
AFTER_FIRST_YEAR_RATE = 0.03


@dataclass(slots=True)
class UserReferralStats:
    """Referrer user statistics (referrals, orders, income, payouts)."""

    creators_count: int
    orders_count: int
    income_current_month: float
    income_total: float
    paid_total: float
    has_pending_payout: bool
    has_request_today: bool


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


def resolve_rate(referred_user: User, order: Order) -> Decimal:
    """Return commission rate for a referred user on an order."""
    if referred_user.referral_payout_rate is not None:
        return referred_user.referral_payout_rate
    completed = order.completed_at or datetime.now(timezone.utc)
    yrs = years_since(referred_user.created_at, completed)
    return Decimal(str(FIRST_YEAR_RATE if yrs < 1.0 else AFTER_FIRST_YEAR_RATE))


def aggregate_payout_requests(
    requests: list[PayoutRequest],
    now: datetime,
) -> tuple[float, bool, bool]:
    """Return (sum of PAID amounts, has_pending, has_request_today)."""
    paid_total = 0.0
    has_pending = False
    has_request_today = False
    now_date = (
        now.date() if now.tzinfo else now.replace(tzinfo=timezone.utc).date()
    )
    for req in requests:
        if req.status == PayoutRequestStatus.PENDING:
            has_pending = True
        if req.status == PayoutRequestStatus.PAID and req.amount is not None:
            paid_total += float(req.amount)
        req_date = (
            req.requested_at.date()
            if req.requested_at.tzinfo
            else req.requested_at.replace(tzinfo=timezone.utc).date()
        )
        if req_date == now_date:
            has_request_today = True
    return (paid_total, has_pending, has_request_today)
