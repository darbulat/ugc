"""Service for calculating referral user income and stats."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from ugc_bot.application.ports import (
    InteractionRepository,
    OfferDispatchRepository,
    OrderRepository,
    PaymentRepository,
    PayoutRequestRepository,
    ReferralOrderIncomeRowLoader,
    TransactionManager,
    UserReferralBindingRepository,
    UserRepository,
)
from ugc_bot.domain.entities import PayoutRequest, User, UserReferralBinding
from ugc_bot.domain.enums import (
    InteractionStatus,
    OrderStatus,
    PaymentStatus,
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


def _effective_rate(
    creator_created_at: datetime,
    order_completed_at: datetime,
    custom_rate: Optional[float],
) -> float:
    """Return rate: custom if set, else default 10% first year, 3% after."""
    if custom_rate is not None:
        return float(custom_rate)
    return _get_rate(creator_created_at, order_completed_at)


@dataclass(slots=True)
class ReferralIncomeService:
    """Calculate referral user income from completed orders."""

    user_referral_binding_repo: UserReferralBindingRepository
    offer_dispatch_repo: OfferDispatchRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    interaction_repo: InteractionRepository
    user_repo: UserRepository
    payout_request_repo: PayoutRequestRepository
    transaction_manager: TransactionManager | None = None
    referral_order_income_loader: ReferralOrderIncomeRowLoader | None = None

    async def get_user_referral_stats(
        self,
        user_id: UUID,
        now: Optional[datetime] = None,
        stats_limit: Optional[int] = None,
    ) -> UserReferralStats:
        """Get referrer statistics: referred users, orders, income.

        Income is from referred bloggers and referred advertisers. Only
        payments in status PAID are counted.

        Bloggers: order CLOSED, referred user in order_responses, interaction
        OK, payment PAID; platform_revenue_per_creator = payment.amount /
        order.bloggers_needed; rate 10% first year, 3% after (from referred
        user registration date).

        Advertisers: order CLOSED, order.advertiser_id = referred user,
        payment PAID; commission = full payment.amount * rate (same 10%/3%).

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

    async def _run_combined_batch_balances(
        self,
        user_ids: List[UUID],
        session: object | None,
    ) -> Dict[UUID, tuple[float, float]]:
        """(income_total, paid_total) per user via combined batch loader."""
        loader = self.referral_order_income_loader
        if loader is None:
            return {}

        users_map = await self.user_repo.get_by_ids(user_ids, session=session)
        custom_rates: Dict[UUID, Optional[float]] = {}
        for uid in user_ids:
            u = users_map.get(uid)
            custom_rates[uid] = (
                float(u.referral_payout_rate)
                if u is not None and u.referral_payout_rate is not None
                else None
            )
        payout_requests = list(
            await self.payout_request_repo.list_by_user_ids(
                user_ids, session=session
            )
        )
        paid_by_user: Dict[UUID, float] = {uid: 0.0 for uid in user_ids}
        for req in payout_requests:
            if (
                req.status == PayoutRequestStatus.PAID
                and req.amount is not None
            ):
                paid_by_user[req.user_id] = paid_by_user.get(
                    req.user_id, 0.0
                ) + float(req.amount)
        rows_with_referrer = (
            await loader.load_referral_order_income_rows_combined_batch(
                referrer_user_ids=user_ids,
                limit=None,
                session=session,
            )
        )
        income_by_user: Dict[UUID, float] = {uid: 0.0 for uid in user_ids}
        for referrer_uid, row in rows_with_referrer:
            if not row.bloggers_needed:
                continue
            rate = _effective_rate(
                row.creator_created_at,
                row.order_completed_at,
                custom_rates.get(referrer_uid),
            )
            platform_revenue = row.payment_amount / row.bloggers_needed
            commission = platform_revenue * rate
            income_by_user[referrer_uid] = (
                income_by_user.get(referrer_uid, 0.0) + commission
            )
        return {
            uid: (
                round(income_by_user.get(uid, 0.0), 2),
                round(paid_by_user.get(uid, 0.0), 2),
            )
            for uid in user_ids
        }

    async def get_referral_balances_batch(
        self,
        user_ids: List[UUID],
        now: Optional[datetime] = None,
        session: object | None = None,
    ) -> Dict[UUID, tuple[float, float]]:
        """(income_total, paid_total) per user_id for dashboard sort/filter.

        Uses batch DB when loader has combined_batch; else
        get_user_referral_stats per user.
        """
        if not user_ids:
            return {}
        if now is None:
            now = datetime.now(timezone.utc)

        loader = self.referral_order_income_loader
        has_batch = loader is not None and callable(
            getattr(
                loader,
                "load_referral_order_income_rows_combined_batch",
                None,
            )
        )

        if has_batch and loader is not None:
            if session is not None:
                return await self._run_combined_batch_balances(
                    user_ids, session
                )

            async def _with_tx(sess: object | None):
                return await self._run_combined_batch_balances(user_ids, sess)

            return await with_optional_tx(self.transaction_manager, _with_tx)

        stats_list = await asyncio.gather(
            *[self.get_user_referral_stats(uid, now=now) for uid in user_ids]
        )
        return {
            uid: (s.income_total, s.paid_total)
            for uid, s in zip(user_ids, stats_list, strict=True)
        }

    async def _compute_income_from_loader(
        self,
        referrer_user_id: UUID,
        limit: int,
        now: datetime,
        session: object,
        custom_rate: Optional[float] = None,
    ) -> tuple[float, float, int]:
        """Compute income from loader rows (bloggers + advertisers)."""
        assert self.referral_order_income_loader is not None
        loader = self.referral_order_income_loader
        combined = getattr(
            loader, "load_referral_order_income_rows_combined", None
        )
        if asyncio.iscoroutinefunction(combined):
            rows = await loader.load_referral_order_income_rows_combined(
                referrer_user_id, limit=limit, session=session
            )
        else:
            rows_bloggers = await loader.load_referral_order_income_rows(
                referrer_user_id, limit=limit, session=session
            )
            rows_advertisers = (
                await loader.load_referral_order_income_rows_advertisers(
                    referrer_user_id, limit=limit, session=session
                )
            )
            rows = rows_bloggers + rows_advertisers
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        income_current_month = 0.0
        income_total = 0.0
        seen_orders: set[UUID] = set()
        for row in rows:
            if not row.bloggers_needed:
                continue
            platform_revenue = row.payment_amount / row.bloggers_needed
            rate = _effective_rate(
                row.creator_created_at, row.order_completed_at, custom_rate
            )
            commission = platform_revenue * rate
            income_total += commission
            seen_orders.add(row.order_id)
            completed_utc = (
                row.order_completed_at
                if row.order_completed_at.tzinfo
                else row.order_completed_at.replace(tzinfo=timezone.utc)
            )
            if (
                completed_utc.month == now_utc.month
                and completed_utc.year == now_utc.year
            ):
                income_current_month += commission
        return income_current_month, income_total, len(seen_orders)

    async def _income_from_advertiser_orders(
        self,
        creator_id: UUID,
        creator: User,
        now_utc: datetime,
        session: object | None,
        custom_rate: Optional[float],
    ) -> tuple[float, float, set[UUID]]:
        """Income from referred user's orders as advertiser (CLOSED, PAID)."""
        income_cm = 0.0
        income_tot = 0.0
        seen: set[UUID] = set()
        orders = list(
            await self.order_repo.list_by_advertiser(
                creator_id, session=session
            )
        )
        for order in orders:
            if order.status != OrderStatus.CLOSED:
                continue
            payment = await self.payment_repo.get_by_order(
                order.order_id, session=session
            )
            if payment is None or payment.status != PaymentStatus.PAID:
                continue
            completed_at = order.completed_at or order.created_at
            rate = _effective_rate(
                creator.created_at, completed_at, custom_rate
            )
            commission = float(payment.amount) * rate
            income_tot += commission
            seen.add(order.order_id)
            completed_at_utc = (
                completed_at
                if completed_at.tzinfo
                else completed_at.replace(tzinfo=timezone.utc)
            )
            if (
                completed_at_utc.month == now_utc.month
                and completed_at_utc.year == now_utc.year
            ):
                income_cm += commission
        return income_cm, income_tot, seen

    async def _compute_income_from_bindings(
        self,
        bindings: list[UserReferralBinding],
        now: datetime,
        session: object | None,
        custom_rate: Optional[float] = None,
    ) -> tuple[float, float, int]:
        """Compute income from bindings (fallback when loader not used)."""
        income_current_month = 0.0
        income_total = 0.0
        seen_orders: set[UUID] = set()
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        for binding in bindings:
            creator_id = binding.referred_user_id
            creator = await self.user_repo.get_by_id(
                creator_id, session=session
            )
            if creator is None:
                continue
            responses = list(
                await self.offer_dispatch_repo.list_responses_by_blogger(
                    creator_id, session=session
                )
            )
            for response in responses:
                if not response.in_offer:
                    continue
                order = await self.order_repo.get_by_id(
                    response.order_id, session=session
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue
                payment = await self.payment_repo.get_by_order(
                    order.order_id, session=session
                )
                if payment is None or payment.status != PaymentStatus.PAID:
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
                rate = _effective_rate(
                    creator.created_at, completed_at, custom_rate
                )
                commission = platform_revenue_per_creator * rate
                income_total += commission
                seen_orders.add(order.order_id)
                completed_at_utc = (
                    completed_at
                    if completed_at.tzinfo
                    else completed_at.replace(tzinfo=timezone.utc)
                )
                if (
                    completed_at_utc.month == now_utc.month
                    and completed_at_utc.year == now_utc.year
                ):
                    income_current_month += commission
            cm, tot, adv_seen = await self._income_from_advertiser_orders(
                creator_id, creator, now_utc, session, custom_rate
            )
            income_current_month += cm
            income_total += tot
            seen_orders |= adv_seen
        return (income_current_month, income_total, len(seen_orders))

    async def _compute_stats(
        self,
        referrer_user_id: UUID,
        now: datetime,
        session: object | None,
        stats_limit: Optional[int] = None,
    ) -> UserReferralStats:
        """Compute referrer stats (runs inside transaction)."""

        referrer = await self.user_repo.get_by_id(
            referrer_user_id, session=session
        )
        custom_rate: Optional[float] = None
        if referrer is not None and referrer.referral_payout_rate is not None:
            custom_rate = float(referrer.referral_payout_rate)

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

        if (
            self.referral_order_income_loader is not None
            and session is not None
        ):
            (
                income_current_month,
                income_total,
                orders_count,
            ) = await self._compute_income_from_loader(
                referrer_user_id,
                effective_limit,
                now,
                session,
                custom_rate=custom_rate,
            )
        else:
            (
                income_current_month,
                income_total,
                orders_count,
            ) = await self._compute_income_from_bindings(
                bindings, now, session, custom_rate=custom_rate
            )

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
            counts = await (
                self.offer_dispatch_repo.count_completed_orders_by_blogger_ids(
                    [user_id], session=sess
                )
            )
            return counts.get(user_id, 0)

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)

    async def count_completed_orders_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        """Count completed orders (CLOSED, OK interaction) per blogger ID."""

        async def _run(sess: object | None) -> Dict[UUID, int]:
            return await (
                self.offer_dispatch_repo.count_completed_orders_by_blogger_ids(
                    user_ids, session=sess
                )
            )

        if session is not None:
            return await _run(session)
        return await with_optional_tx(self.transaction_manager, _run)
