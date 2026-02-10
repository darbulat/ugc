"""Service for calculating referral user income and stats."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    InteractionRepository,
    OrderRepository,
    OrderResponseRepository,
    PaymentRepository,
    PayoutRequestRepository,
    TransactionManager,
    UserReferralBindingRepository,
    UserRepository,
)
from ugc_bot.domain.entities import PayoutRequest
from ugc_bot.domain.enums import (
    InteractionStatus,
    OrderStatus,
    PayoutRequestStatus,
)
from ugc_bot.infrastructure.db.session import with_optional_tx


def _aggregate_payout_requests(
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


def _years_since(date: datetime, reference: datetime) -> float:
    """Return years between date and reference (can be fractional)."""

    delta = reference - date
    return delta.total_seconds() / (365.25 * 24 * 3600)


def _get_rate(
    creator_created_at: datetime, order_completed_at: datetime
) -> float:
    """Return commission rate: 10% first year, 3% after."""

    years = _years_since(creator_created_at, order_completed_at)
    return FIRST_YEAR_RATE if years < 1.0 else AFTER_FIRST_YEAR_RATE


@dataclass(slots=True)
class ReferralIncomeService:
    """Calculate referral user income from completed orders."""

    user_referral_binding_repo: UserReferralBindingRepository
    order_response_repo: OrderResponseRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    interaction_repo: InteractionRepository
    user_repo: UserRepository
    payout_request_repo: PayoutRequestRepository
    transaction_manager: TransactionManager | None = None

    async def get_user_referral_stats(
        self,
        user_id: UUID,
        now: Optional[datetime] = None,
        stats_limit: Optional[int] = None,
    ) -> UserReferralStats:
        """Get referrer statistics: referred users, orders, income.

        Income is calculated from orders where:
        - Order status is CLOSED
        - Referred user is in order_responses
        - Interaction status is OK (good feedback from advertiser)
        - platform_revenue_per_creator = payment.amount / order.bloggers_needed
        - Rate: 10% first year, 3% after (from referred user registration date)

        stats_limit: max referrals to include in stats (default 10_000;
           0 or None = use default. Set 0 in config for unlimited).
        """

        if now is None:
            now = datetime.now(timezone.utc)

        async def _run(session: object | None) -> UserReferralStats:
            return await self._compute_stats(
                user_id, now, session, stats_limit=stats_limit
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def _compute_stats(
        self,
        referrer_user_id: UUID,
        now: datetime,
        session: object | None,
        stats_limit: Optional[int] = None,
    ) -> UserReferralStats:
        """Compute referrer stats (runs inside transaction)."""

        effective_limit = 10_000 if stats_limit is None else stats_limit
        if effective_limit <= 0:
            effective_limit = 10_000_000

        bindings = list(
            await self.user_referral_binding_repo.list_by_referrer(
                referrer_user_id,
                offset=0,
                limit=effective_limit,
                session=session,
            )
        )
        creators_count = len(bindings)

        income_current_month = 0.0
        income_total = 0.0
        seen_orders: set[UUID] = set()

        for binding in bindings:
            creator_id = binding.referred_user_id
            creator = await self.user_repo.get_by_id(
                creator_id, session=session
            )
            if creator is None:
                continue

            responses = list(
                await self.order_response_repo.list_by_blogger(
                    creator_id, session=session
                )
            )

            for response in responses:
                order = await self.order_repo.get_by_id(
                    response.order_id, session=session
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue

                payment = await self.payment_repo.get_by_order(
                    order.order_id, session=session
                )
                if payment is None:
                    continue

                interaction = await self.interaction_repo.get_by_participants(
                    order_id=order.order_id,
                    blogger_id=creator_id,
                    advertiser_id=order.advertiser_id,
                    session=session,
                )
                if (
                    interaction is None
                    or interaction.status != InteractionStatus.OK
                ):
                    continue

                if order.bloggers_needed <= 0:
                    continue

                completed_at = order.completed_at or order.created_at
                platform_revenue_per_creator = (
                    float(payment.amount) / order.bloggers_needed
                )
                rate = _get_rate(creator.created_at, completed_at)
                commission = platform_revenue_per_creator * rate

                income_total += commission
                seen_orders.add(order.order_id)

                completed_at_utc = (
                    completed_at
                    if completed_at.tzinfo
                    else completed_at.replace(tzinfo=timezone.utc)
                )
                now_utc = (
                    now if now.tzinfo else now.replace(tzinfo=timezone.utc)
                )
                if (
                    completed_at_utc.month == now_utc.month
                    and completed_at_utc.year == now_utc.year
                ):
                    income_current_month += commission

        orders_count = len(seen_orders)

        payout_requests = list(
            await self.payout_request_repo.list_by_user(
                referrer_user_id, session=session
            )
        )
        paid_total, has_pending_payout, has_request_today = (
            _aggregate_payout_requests(payout_requests, now)
        )

        return UserReferralStats(
            creators_count=creators_count,
            orders_count=orders_count,
            income_current_month=round(income_current_month, 2),
            income_total=round(income_total, 2),
            paid_total=round(paid_total, 2),
            has_pending_payout=has_pending_payout,
            has_request_today=has_request_today,
        )

    async def count_completed_orders_for_user(
        self,
        user_id: UUID,
        session: object | None = None,
    ) -> int:
        """Count completed orders (CLOSED, OK interaction) for blogger user."""

        async def _run(sess: object | None) -> int:
            count = 0
            responses = list(
                await self.order_response_repo.list_by_blogger(
                    user_id, session=sess
                )
            )
            for response in responses:
                order = await self.order_repo.get_by_id(
                    response.order_id, session=sess
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue
                interaction = await self.interaction_repo.get_by_participants(
                    order_id=order.order_id,
                    blogger_id=user_id,
                    advertiser_id=order.advertiser_id,
                    session=sess,
                )
                if (
                    interaction is not None
                    and interaction.status == InteractionStatus.OK
                ):
                    count += 1
            return count

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)
