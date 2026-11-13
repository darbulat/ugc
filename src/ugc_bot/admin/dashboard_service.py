"""Admin dashboard aggregation service."""

import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import String, and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from ugc_bot.admin.complaints import (
    COMPLAINT_STATUS_LABELS,
    OPEN_COMPLAINT_STATUSES,
)
from ugc_bot.admin.order_worklist import (
    aging_unpaid_condition,
    worklist_conditions,
)
from ugc_bot.domain.enums import (
    OrderStatus,
    PaymentStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.dispatch_control import CONTROLS
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    PayoutRequestModel,
    UserModel,
    UserReferralBindingModel,
)

if TYPE_CHECKING:
    from ugc_bot.application.services.offer_dispatch_service import (
        OfferDispatchService,
    )
    from ugc_bot.application.services.referral_income_service import (
        ReferralIncomeService,
    )

PeriodKey = Literal["today", "yesterday", "7d", "30d", "all"]

_ACTIVE_ORDER_STATUSES = (
    OrderStatus.NEW,
    OrderStatus.PENDING_MODERATION,
    OrderStatus.ACTIVE,
)

PICKED_CREATORS_TARGET = 1000

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PeriodWindow:
    """Time window for current and previous periods."""

    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime


def dashboard_period_window(
    period: PeriodKey, timezone: ZoneInfo
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
        previous_end = start_of_today
        previous_start = previous_end - timedelta(days=1)
    elif period == "yesterday":
        current_end = start_of_today
        current_start = current_end - timedelta(days=1)
        previous_end = current_start
        previous_start = previous_end - timedelta(days=1)
    elif period == "7d":
        current_end = now
        current_start = now - timedelta(days=7)
        previous_end = current_start
        previous_start = previous_end - timedelta(days=7)
    elif period == "30d":
        current_end = now
        current_start = now - timedelta(days=30)
        previous_end = current_start
        previous_start = previous_end - timedelta(days=30)
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


def paid_in_period(window: PeriodWindow) -> ColumnElement[bool]:
    paid_at = func.coalesce(PaymentModel.paid_at, PaymentModel.created_at)
    return and_(
        PaymentModel.status == PaymentStatus.PAID,
        paid_at >= window.current_start,
        paid_at < window.current_end,
    )


@dataclass(slots=True)
class DelayThresholds:
    """Thresholds for delayed orders detection."""

    active_days: int
    no_responses_hours: int
    low_picked_hours: int
    archive_days: int


@dataclass(slots=True)
class OrderCard:
    """Order card values for dashboards and lists."""

    order_id: UUID
    advertiser_name: str
    status_label: str
    created_at: datetime
    completed_at: datetime | None
    picked_count: int
    needed_count: int
    status_age_hours: float
    has_problem: bool


def _paginated(total: int, page: int, per_page: int, items: list) -> dict:
    """Build paginated result: items, total, page, per_page, total_pages."""
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


class AdminDashboardService:
    """Aggregate operational metrics for the admin dashboard."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        timezone_name: str,
        thresholds: DelayThresholds,
        referral_income_service: "ReferralIncomeService | None" = None,
        offer_dispatch_service: "OfferDispatchService | None" = None,
    ) -> None:
        """Initialize dashboard service dependencies."""
        self._session_factory = session_factory
        self._timezone = ZoneInfo(timezone_name)
        self._thresholds = thresholds
        self._referral_income_service = referral_income_service
        self._offer_dispatch_service = offer_dispatch_service

    async def get_dashboard(
        self,
        period: PeriodKey,
        referrers_page: int = 1,
        referrers_per_page: int = 25,
        referrers_sort: str | None = None,
        referrers_order: str = "desc",
        referrers_filter: str | None = None,
        include_timings: bool = False,
    ) -> dict:
        """Return dashboard cards and delayed orders list."""
        total_start = time.perf_counter()
        timings: dict[str, float] = {}
        window = self._build_period_window(period)
        async with self._session_factory() as session:
            t0 = time.perf_counter()
            registrations = await self._get_registration_cards(session, window)
            timings["registrations"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            orders = await self._get_order_cards(session, window)
            timings["orders"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            open_complaints = await self._count_open_complaints(session)
            timings["open_complaints"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            open_complaints_list = await self._list_open_complaints(session)
            timings["open_complaints_list"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            attention = await self._get_order_attention(session)
            delayed_orders = attention["delayed"]
            timings["delayed_orders"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            referrers = await self._get_referral_referrers(session, window)
            timings["referrers"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            payout_requests = await self._list_payout_requests(session)
            timings["payout_requests"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            payments = await self._paid_totals(session, window)
            timings["turnover"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            creators_by_city = await self._get_creators_by_city(session)
            timings["creators_by_city"] = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            picked_creators_count = await self._count_picked_creators(session)
            timings["picked_creators"] = (time.perf_counter() - t0) * 1000
        page = max(1, referrers_page)
        per_page = max(1, min(100, referrers_per_page))
        need_balance_for_filter = referrers_filter in (
            "top_by_balance",
            "top_by_earnings_period",
        )
        t0 = time.perf_counter()
        if need_balance_for_filter:
            referral_data = await self._referrers_balance_filter_sort_paginate(
                referrers=referrers,
                referrers_filter=referrers_filter,
                referrers_sort=referrers_sort,
                referrers_order=referrers_order,
                page=page,
                per_page=per_page,
            )
            total_referrers = referral_data["referrers_total"]
            total_pages = (
                (total_referrers + per_page - 1) // per_page
                if total_referrers
                else 1
            )
        else:
            filtered = self._apply_referrers_filter(referrers, referrers_filter)
            default_sort = self._referrers_filter_default_sort(referrers_filter)
            sorted_refs = self._sort_referrers(
                filtered,
                referrers_sort or default_sort or "total_referred",
                referrers_order,
            )
            total_referrers = len(sorted_refs)
            total_pages = (
                (total_referrers + per_page - 1) // per_page
                if total_referrers
                else 1
            )
            start = (page - 1) * per_page
            page_referrers = sorted_refs[start : start + per_page]
            use_totals = total_referrers <= per_page
            referral_data = await self._enrich_referrers_with_balance(
                page_referrers, sort_by_balance=use_totals
            )
        timings["enrich_referrers"] = (time.perf_counter() - t0) * 1000
        referral_data["referrers_total"] = total_referrers
        referral_data["referrers_page"] = page
        referral_data["referrers_per_page"] = per_page
        referral_data["referrers_total_pages"] = total_pages
        referral_data["referrers_sort"] = (
            referrers_sort
            or self._referrers_filter_default_sort(referrers_filter)
            or "balance"
        )
        referral_data["referrers_order"] = (
            "asc" if referrers_order == "asc" else "desc"
        )
        referral_data["referrers_filter"] = referrers_filter or "all"
        total_ms = (time.perf_counter() - total_start) * 1000
        timings["_total"] = total_ms
        logger.info(
            "dashboard timings period=%s total=%.0fms %s",
            period,
            total_ms,
            " ".join(
                f"{k}={v:.0f}ms"
                for k, v in sorted(timings.items())
                if not k.startswith("_")
            ),
        )
        creators_count = registrations["creators"]["count"]
        advertisers_count = registrations["advertisers"]["count"]
        ratio = (
            creators_count / advertisers_count
            if advertisers_count
            else (float(creators_count) if creators_count else 0.0)
        )
        result = {
            "period": period,
            "registrations": registrations,
            "imbalance": {
                "creators": creators_count,
                "advertisers": advertisers_count,
                "ratio": round(ratio, 2) if advertisers_count else None,
                "label": (
                    f"{creators_count} креаторов / "
                    + (
                        f"{advertisers_count} заказчиков"
                        if advertisers_count
                        else "0 заказчиков"
                    )
                ),
            },
            "orders": orders,
            "problems": {
                "open_complaints": open_complaints,
                "delays": len(delayed_orders),
            },
            "delayed_orders": delayed_orders,
            "order_attention": attention,
            "open_complaints_list": open_complaints_list,
            "referrals": referral_data,
            "payout_requests": payout_requests,
            "payments_by_currency": payments,
            "paid_orders": sum(row["count"] for row in payments),
            "turnover_period": (
                float(payments[0]["amount"])
                if len(payments) == 1
                else None
                if payments
                else 0.0
            ),
            "creators_by_city": creators_by_city,
            "picked_creators_count": picked_creators_count,
            "picked_creators_target": PICKED_CREATORS_TARGET,
        }
        if include_timings:
            result["_timings_ms"] = timings
        return result

    async def get_dashboard_charts(self, period: PeriodKey) -> dict:
        """Return time-series data for dashboard charts (by day)."""
        window = self._build_period_window(period)
        async with self._session_factory() as session:
            reg_creators = await self._chart_registrations_by_day(
                session,
                BloggerProfileModel,
                window.current_start,
                window.current_end,
            )
            reg_advertisers = await self._chart_registrations_by_day(
                session,
                AdvertiserProfileModel,
                window.current_start,
                window.current_end,
            )
            orders = await self._chart_orders_by_day(
                session,
                window.current_start,
                window.current_end,
            )
            turnover = await self._chart_turnover_by_day(
                session,
                window.current_start,
                window.current_end,
            )
        return {
            "registrations_creators": reg_creators,
            "registrations_advertisers": reg_advertisers,
            "orders": orders,
            "turnover": turnover,
        }

    async def _chart_registrations_by_day(
        self,
        session: AsyncSession,
        profile_model: type[Any],
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Count registrations by day (users with profile created in range)."""
        day = func.date_trunc("day", UserModel.created_at)
        query = (
            select(
                day.label("day"),
                func.count(UserModel.user_id).label("count"),
            )
            .select_from(UserModel)
            .join(profile_model, profile_model.user_id == UserModel.user_id)
            .where(
                and_(UserModel.created_at >= start, UserModel.created_at < end)
            )
            .group_by(day)
            .order_by(day)
        )
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "date": row.day.strftime("%Y-%m-%d") if row.day else "",
                "count": int(row[1]),
            }
            for row in rows
        ]

    async def _chart_orders_by_day(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Count orders created by day."""
        day = func.date_trunc("day", OrderModel.created_at)
        query = (
            select(
                day.label("day"), func.count(OrderModel.order_id).label("count")
            )
            .select_from(OrderModel)
            .where(
                *worklist_conditions("all", ""),
                and_(
                    OrderModel.created_at >= start,
                    OrderModel.created_at < end,
                ),
            )
            .group_by(day)
            .order_by(day)
        )
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "date": row.day.strftime("%Y-%m-%d") if row.day else "",
                "count": int(row[1]),
            }
            for row in rows
        ]

    async def _paid_totals(
        self,
        session: AsyncSession,
        window: PeriodWindow,
    ) -> list[dict]:
        """Total paid orders and amount per currency for the period."""
        query = (
            select(
                PaymentModel.currency,
                func.count(distinct(PaymentModel.order_id)),
                func.sum(PaymentModel.amount),
            )
            .select_from(PaymentModel)
            .where(paid_in_period(window))
            .group_by(PaymentModel.currency)
            .order_by(PaymentModel.currency)
        )
        result = await session.execute(query)
        return [
            {
                "currency": currency,
                "count": int(count),
                "amount": format(Decimal(str(amount)), ".2f"),
            }
            for currency, count, amount in result.all()
        ]

    async def _chart_turnover_by_day(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Sum paid payment amounts by day (paid_at or created_at)."""
        date_col = func.coalesce(PaymentModel.paid_at, PaymentModel.created_at)
        day = func.date_trunc("day", date_col)
        query = (
            select(
                day.label("day"),
                PaymentModel.currency,
                func.coalesce(func.sum(PaymentModel.amount), 0).label("amount"),
            )
            .select_from(PaymentModel)
            .where(
                and_(
                    PaymentModel.status == PaymentStatus.PAID,
                    date_col >= start,
                    date_col < end,
                )
            )
            .group_by(day, PaymentModel.currency)
            .order_by(day, PaymentModel.currency)
        )
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "date": row.day.strftime("%Y-%m-%d") if row.day else "",
                "currency": row.currency,
                "amount": round(float(row.amount), 2),
            }
            for row in rows
        ]

    async def list_creators(
        self,
        period: PeriodKey,
        only_new: bool,
        only_with_complaints: bool,
        page: int = 1,
        per_page: int = 25,
        q: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        """Return paginated creator list with counts and filters."""
        window = self._build_period_window(period)
        page = max(1, page)
        per_page = max(1, min(100, per_page))
        search_query = (q or "").strip() or None
        async with self._session_factory() as session:
            total = await self._count_creators(
                session, window, only_new, only_with_complaints, search_query
            )
            items = await self._list_creators(
                session,
                window,
                only_new,
                only_with_complaints,
                limit=per_page,
                offset=(page - 1) * per_page,
                search_query=search_query,
                sort_by=sort,
                order_asc=order == "asc",
            )
        return _paginated(total, page, per_page, items)

    async def list_advertisers(
        self,
        page: int = 1,
        per_page: int = 25,
        q: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        """Return paginated advertiser list with order and complaint counts."""
        page = max(1, page)
        per_page = max(1, min(100, per_page))
        search_query = (q or "").strip() or None
        async with self._session_factory() as session:
            total = await self._count_advertisers(session, search_query)
            items = await self._list_advertisers(
                session,
                limit=per_page,
                offset=(page - 1) * per_page,
                search_query=search_query,
                sort_by=sort,
                order_asc=order == "asc",
            )
        return _paginated(total, page, per_page, items)

    async def list_orders(
        self,
        period: PeriodKey,
        status_filter: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
        search: str | None = None,
    ) -> dict:
        """Return paginated order list for the selected period."""
        window = self._build_period_window(period)
        page = max(1, page)
        per_page = max(1, min(100, per_page))
        search_term = search.strip() if search else None
        if search_term == "":
            search_term = None
        async with self._session_factory() as session:
            total = await self._count_orders(
                session, window, status_filter, search_term
            )
            items = await self._list_orders(
                session,
                window,
                status_filter,
                limit=per_page,
                offset=(page - 1) * per_page,
                sort_by=sort,
                order_asc=order == "asc",
                search=search_term,
            )
        return _paginated(total, page, per_page, items)

    async def get_order_card(self, order_id: UUID) -> dict | None:
        """Return detailed order card data for a single order."""
        async with self._session_factory() as session:
            return await self._get_order_card(session, order_id)

    def _build_period_window(self, period: PeriodKey) -> PeriodWindow:
        return dashboard_period_window(period, self._timezone)

    async def _get_registration_cards(
        self, session: AsyncSession, window: PeriodWindow
    ) -> dict:
        """Return creator and advertiser registration cards."""
        creators_current = await self._count_users_with_profile(
            session,
            BloggerProfileModel,
            window.current_start,
            window.current_end,
        )
        creators_prev = await self._count_users_with_profile(
            session,
            BloggerProfileModel,
            window.previous_start,
            window.previous_end,
        )
        advertisers_current = await self._count_users_with_profile(
            session,
            AdvertiserProfileModel,
            window.current_start,
            window.current_end,
        )
        advertisers_prev = await self._count_users_with_profile(
            session,
            AdvertiserProfileModel,
            window.previous_start,
            window.previous_end,
        )
        return {
            "creators": self._build_delta(creators_current, creators_prev),
            "advertisers": self._build_delta(
                advertisers_current, advertisers_prev
            ),
        }

    async def get_creators_by_city(self) -> list[dict[str, Any]]:
        """Return creators count grouped by city, sorted by count descending."""
        async with self._session_factory() as session:
            return await self._get_creators_by_city(session)

    async def _get_creators_by_city(
        self, session: AsyncSession
    ) -> list[dict[str, Any]]:
        """Return creators count grouped by city, sorted by count descending."""
        query = (
            select(
                BloggerProfileModel.city,
                func.count(BloggerProfileModel.user_id).label("count"),
            )
            .group_by(BloggerProfileModel.city)
            .order_by(func.count(BloggerProfileModel.user_id).desc())
        )
        result = await session.execute(query)
        rows = result.all()
        return [{"city": row[0], "count": int(row[1])} for row in rows]

    async def _get_order_cards(
        self, session: AsyncSession, window: PeriodWindow
    ) -> dict:
        """Return order cards (active/completed/archived) in one query."""
        responses = self._order_responses_subquery()
        open_complaints = self._open_complaints_subquery()
        resp = func.coalesce(responses.c.responses, 0)
        open_c = func.coalesce(open_complaints.c.open_complaints, 0)
        completed_expr = (OrderModel.status == OrderStatus.CLOSED) | (
            resp >= OrderModel.bloggers_needed
        )
        cutoff = datetime.now(self._timezone) - timedelta(
            days=self._thresholds.archive_days
        )
        archived_expr = and_(
            completed_expr,
            OrderModel.completed_at.isnot(None),
            open_c == 0,
            OrderModel.completed_at < cutoff,
        )
        active_expr = ~completed_expr
        completed_only_expr = completed_expr & ~archived_expr
        query = (
            select(
                func.sum(case((active_expr, 1), else_=0)).label("active"),
                func.sum(case((completed_only_expr, 1), else_=0)).label(
                    "completed"
                ),
                func.sum(case((archived_expr, 1), else_=0)).label("archived"),
            )
            .select_from(OrderModel)
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .outerjoin(
                open_complaints,
                open_complaints.c.order_id == OrderModel.order_id,
            )
            .where(
                *worklist_conditions("all", ""),
                and_(
                    OrderModel.created_at >= window.current_start,
                    OrderModel.created_at < window.current_end,
                ),
            )
        )
        result = await session.execute(query)
        row = result.one()
        return {
            "active": int(row.active or 0),
            "completed": int(row.completed or 0),
            "archived": int(row.archived or 0),
        }

    async def _count_open_complaints(self, session: AsyncSession) -> int:
        """Count open complaints across all orders."""
        query = select(func.count(ComplaintModel.complaint_id)).where(
            ComplaintModel.status.in_(OPEN_COMPLAINT_STATUSES)
        )
        result = await session.execute(query)
        return int(result.scalar() or 0)

    async def _count_picked_creators(self, session: AsyncSession) -> int:
        """Count unique creators with at least one in_offer dispatch."""
        query = (
            select(func.count(distinct(OfferDispatchModel.blogger_id)))
            .select_from(OfferDispatchModel)
            .where(OfferDispatchModel.in_offer.is_(True))
        )
        result = await session.execute(query)
        return int(result.scalar() or 0)

    async def _list_open_complaints(
        self, session: AsyncSession, limit: int = 50
    ) -> list[dict]:
        """Return list of open complaints with reporter/reported names."""
        Reporter = aliased(UserModel, name="reporter")
        Reported = aliased(UserModel, name="reported")
        query = (
            select(
                ComplaintModel.complaint_id,
                ComplaintModel.order_id,
                ComplaintModel.reason,
                ComplaintModel.created_at,
                ComplaintModel.status,
                Reporter.username.label("reporter_username"),
                Reporter.telegram.label("reporter_telegram"),
                Reported.username.label("reported_username"),
                Reported.telegram.label("reported_telegram"),
            )
            .select_from(ComplaintModel)
            .join(Reporter, Reporter.user_id == ComplaintModel.reporter_id)
            .join(Reported, Reported.user_id == ComplaintModel.reported_id)
            .where(ComplaintModel.status.in_(OPEN_COMPLAINT_STATUSES))
            .order_by(ComplaintModel.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "complaint_id": str(row.complaint_id),
                "order_id": str(row.order_id),
                "reason": row.reason or "",
                "created_at": row.created_at,
                "status": row.status.value if row.status else "",
                "status_label": COMPLAINT_STATUS_LABELS.get(
                    row.status, row.status.value if row.status else ""
                ),
                "reporter": row.reporter_telegram
                or row.reporter_username
                or "",
                "reported": row.reported_telegram
                or row.reported_username
                or "",
            }
            for row in rows
        ]

    async def _get_referral_referrers(
        self, session: AsyncSession, window: PeriodWindow
    ) -> list[dict]:
        """Return referral analytics per referrer (managers) for dashboard."""
        bindings = UserReferralBindingModel
        total_subq = (
            select(func.count(bindings.referred_user_id))
            .where(bindings.referrer_user_id == UserModel.user_id)
            .scalar_subquery()
        )
        creators_subq = (
            select(func.count(bindings.referred_user_id))
            .select_from(bindings)
            .join(
                BloggerProfileModel,
                BloggerProfileModel.user_id == bindings.referred_user_id,
            )
            .where(bindings.referrer_user_id == UserModel.user_id)
            .scalar_subquery()
        )
        advertisers_subq = (
            select(func.count(bindings.referred_user_id))
            .select_from(bindings)
            .join(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == bindings.referred_user_id,
            )
            .where(bindings.referrer_user_id == UserModel.user_id)
            .scalar_subquery()
        )
        new_in_period_subq = (
            select(func.count(bindings.referred_user_id))
            .where(bindings.referrer_user_id == UserModel.user_id)
            .where(bindings.created_at >= window.current_start)
            .where(bindings.created_at < window.current_end)
            .scalar_subquery()
        )
        query = select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            UserModel.referral_code,
            func.coalesce(total_subq, 0).label("total_referred"),
            func.coalesce(creators_subq, 0).label("referred_creators"),
            func.coalesce(advertisers_subq, 0).label("referred_advertisers"),
            func.coalesce(new_in_period_subq, 0).label("new_in_period"),
        ).where(UserModel.referral_code.isnot(None))
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "user_id": str(row.user_id),
                "username": row.username,
                "telegram": row.telegram,
                "referral_code": row.referral_code or "",
                "total_referred": int(row.total_referred),
                "referred_creators": int(row.referred_creators),
                "referred_advertisers": int(row.referred_advertisers),
                "new_in_period": int(row.new_in_period),
            }
            for row in rows
        ]

    async def _referrers_balance_filter_sort_paginate(
        self,
        referrers: list[dict],
        referrers_filter: str | None,
        referrers_sort: str | None,
        referrers_order: str,
        page: int,
        per_page: int,
    ) -> dict:
        """Batch balances, then filter, sort and paginate referrers."""
        total_earned: float | None = None
        total_balance: float | None = None
        if not referrers:
            return {
                "referrers": [],
                "total_earned": total_earned,
                "total_balance": total_balance,
                "referrers_total": 0,
            }
        service = self._referral_income_service
        if service is None:
            for r in referrers:
                r["balance"] = None
            refs = self._apply_referrers_filter(referrers, referrers_filter)
            refs = self._sort_referrers(
                refs,
                referrers_sort
                or self._referrers_filter_default_sort(referrers_filter),
                referrers_order,
            )
            total_referrers = len(refs)
            start = (page - 1) * per_page
            return {
                "referrers": refs[start : start + per_page],
                "total_earned": total_earned,
                "total_balance": total_balance,
                "referrers_total": total_referrers,
            }
        user_ids = [UUID(r["user_id"]) for r in referrers]
        balances = await service.get_referral_balances_batch(user_ids)
        for r in referrers:
            inc, paid = balances.get(UUID(r["user_id"]), (0.0, 0.0))
            r["balance"] = round(inc - paid, 2)
        refs = self._apply_referrers_filter(referrers, referrers_filter)
        refs = self._sort_referrers(
            refs,
            referrers_sort
            or self._referrers_filter_default_sort(referrers_filter),
            referrers_order,
        )
        total_referrers = len(refs)
        total_earned = round(
            sum(balances.get(UUID(r["user_id"]), (0.0, 0.0))[0] for r in refs),
            2,
        )
        total_balance = round(sum(r.get("balance") or 0.0 for r in refs), 2)
        start = (page - 1) * per_page
        return {
            "referrers": refs[start : start + per_page],
            "total_earned": total_earned,
            "total_balance": total_balance,
            "referrers_total": total_referrers,
        }

    async def _enrich_referrers_with_balance(
        self,
        referrers: list[dict],
        sort_by_balance: bool = True,
    ) -> dict:
        """Add balance; optionally sort by balance and sum totals."""
        total_earned: float | None = None
        total_balance: float | None = None
        if not referrers:
            return {
                "referrers": referrers,
                "total_earned": total_earned,
                "total_balance": total_balance,
            }
        service = self._referral_income_service
        if service is None:
            for r in referrers:
                r["balance"] = None
            if sort_by_balance:
                referrers.sort(
                    key=lambda x: (x["total_referred"], x["user_id"]),
                    reverse=True,
                )
            return {
                "referrers": referrers,
                "total_earned": total_earned,
                "total_balance": total_balance,
            }
        user_ids = [UUID(r["user_id"]) for r in referrers]
        balances = await service.get_referral_balances_batch(user_ids)
        sum_earned = 0.0
        sum_balance = 0.0
        for r in referrers:
            uid = UUID(r["user_id"])
            inc, paid = balances.get(uid, (0.0, 0.0))
            balance = round(inc - paid, 2)
            r["balance"] = balance
            if sort_by_balance:
                sum_earned += inc
                sum_balance += balance
        if sort_by_balance:
            total_earned = round(sum_earned, 2)
            total_balance = round(sum_balance, 2)
            referrers.sort(
                key=lambda x: (x["balance"] or 0.0, x["user_id"]),
                reverse=True,
            )
        return {
            "referrers": referrers,
            "total_earned": total_earned,
            "total_balance": total_balance,
        }

    async def _list_payout_requests(self, session: AsyncSession) -> list[dict]:
        """Return recent payout requests with referrer telegram/username."""
        query = (
            select(
                PayoutRequestModel.request_id,
                PayoutRequestModel.user_id,
                UserModel.username,
                UserModel.telegram,
                PayoutRequestModel.requested_at,
                PayoutRequestModel.status,
                PayoutRequestModel.amount,
                PayoutRequestModel.currency,
            )
            .join(
                UserModel,
                UserModel.user_id == PayoutRequestModel.user_id,
            )
            .order_by(PayoutRequestModel.requested_at.desc())
            .limit(100)
        )
        result = await session.execute(query)
        rows = result.all()
        status_labels = {
            PayoutRequestStatus.PENDING: "Ожидает",
            PayoutRequestStatus.PAID: "Выплачено",
            PayoutRequestStatus.CANCELLED: "Отменено",
        }
        return [
            {
                "request_id": str(row.request_id),
                "user_id": str(row.user_id),
                "username": row.username,
                "telegram": row.telegram,
                "requested_at": row.requested_at,
                "status": row.status.value if row.status else "",
                "status_label": status_labels.get(
                    row.status, row.status.value if row.status else ""
                ),
                "amount": float(row.amount) if row.amount is not None else None,
                "currency": row.currency,
            }
            for row in rows
        ]

    async def get_user_card(self, user_id: UUID) -> dict | None:
        """Return user card with profiles for read-only view."""
        async with self._session_factory() as session:
            return await self._get_user_card(session, user_id)

    async def search_users(self, query: str, limit: int = 20) -> list[dict]:
        """Search users by username, telegram or external_id (exact)."""
        if not query or not query.strip():
            return []
        q = query.strip()
        async with self._session_factory() as session:
            conditions: list[ColumnElement[bool]] = [
                UserModel.username.ilike(f"%{q}%"),
                UserModel.telegram.ilike(f"%{q}%"),
            ]
            with contextlib.suppress(ValueError, TypeError):
                conditions.append(UserModel.user_id == UUID(q))  # type: ignore[arg-type]
            if q.isdigit():
                conditions.append(UserModel.telegram_id == q)  # type: ignore[arg-type]
                conditions.append(UserModel.max_id == q)  # type: ignore[arg-type]
            stmt = (
                select(
                    UserModel.user_id,
                    UserModel.username,
                    UserModel.telegram,
                    UserModel.telegram_id,
                    UserModel.max_id,
                )
                .where(or_(*conditions))
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.all()
            return [
                {
                    "user_id": str(row.user_id),
                    "username": row.username or "",
                    "telegram": row.telegram or "",
                    "telegram_id": row.telegram_id or "",
                    "max_id": row.max_id or "",
                }
                for row in rows
            ]

    async def _get_user_card(
        self, session: AsyncSession, user_id: UUID
    ) -> dict | None:
        """Load user with optional blogger and advertiser profiles."""
        query = (
            select(UserModel, BloggerProfileModel, AdvertiserProfileModel)
            .outerjoin(
                BloggerProfileModel,
                BloggerProfileModel.user_id == UserModel.user_id,
            )
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == UserModel.user_id,
            )
            .where(UserModel.user_id == user_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()
        if row is None:
            return None
        user, blogger, advertiser = row
        card: dict = {
            "user_id": str(user.user_id),
            "telegram_id": user.telegram_id or "",
            "max_id": user.max_id or "",
            "messenger_type": user.messenger_type.value
            if user.messenger_type
            else "",
            "username": user.username,
            "status": user.status.value if user.status else "",
            "status_label": self._user_status_label(user.status),
            "issue_count": int(user.issue_count),
            "created_at": user.created_at,
            "role_chosen_at": user.role_chosen_at,
            "last_role_reminder_at": user.last_role_reminder_at,
            "telegram": user.telegram,
            "admin": user.admin,
            "referral_code": user.referral_code,
        }
        if blogger is not None:
            card["blogger_profile"] = {
                "instagram_url": blogger.instagram_url,
                "confirmed": blogger.confirmed,
                "city": blogger.city,
                "blogger_gender": getattr(
                    blogger.blogger_gender,
                    "value",
                    str(blogger.blogger_gender),
                )
                if getattr(blogger, "blogger_gender", None)
                else "",
                "topics": blogger.topics,
                "audience_gender": getattr(
                    blogger.audience_gender,
                    "value",
                    str(blogger.audience_gender),
                )
                if blogger.audience_gender
                else "",
                "audience_age_min": int(blogger.audience_age_min),
                "audience_age_max": int(blogger.audience_age_max),
                "audience_geo": blogger.audience_geo,
                "price": float(blogger.price),
                "barter": blogger.barter,
                "work_format": getattr(
                    blogger.work_format, "value", str(blogger.work_format)
                )
                if blogger.work_format
                else "",
                "wanted_to_change_terms_count": int(
                    blogger.wanted_to_change_terms_count
                ),
                "updated_at": blogger.updated_at,
            }
        else:
            card["blogger_profile"] = None
        if advertiser is not None:
            card["advertiser_profile"] = {
                "contact": advertiser.contact,
                "brand": advertiser.brand,
                "site_link": advertiser.site_link,
                "city": advertiser.city,
                "company_activity": advertiser.company_activity,
            }
        else:
            card["advertiser_profile"] = None
        return card

    async def _get_order_attention(self, session: AsyncSession) -> dict:
        """Group current orders by the action they are waiting for."""
        now = datetime.now(timezone.utc)
        responses = self._order_responses_subquery()
        complaint_counts = self._open_complaints_subquery()
        query = (
            select(
                OrderModel,
                func.coalesce(responses.c.responses, 0).label("responses"),
                func.coalesce(complaint_counts.c.open_complaints, 0).label(
                    "open_complaints"
                ),
                func.coalesce(
                    AdvertiserProfileModel.brand, UserModel.username
                ).label("advertiser_name"),
                PaymentModel.status.label("payment_status"),
                CONTROLS.c.paused.label("paused"),
                aging_unpaid_condition(
                    now, self._thresholds.no_responses_hours
                ).label("aging_unpaid"),
            )
            .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            )
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .outerjoin(
                complaint_counts,
                complaint_counts.c.order_id == OrderModel.order_id,
            )
            .outerjoin(
                PaymentModel, PaymentModel.order_id == OrderModel.order_id
            )
            .outerjoin(CONTROLS, CONTROLS.c.order_id == OrderModel.order_id)
            .where(
                *worklist_conditions("work", ""),
                OrderModel.status.in_(_ACTIVE_ORDER_STATUSES),
            )
            .order_by(OrderModel.created_at, OrderModel.order_id)
        )
        result = await session.execute(query)
        rows = result.all()
        attention: dict[str, Any] = {
            "active": 0,
            "delayed": [],
            "unpaid": [],
            "moderation": [],
        }
        for (
            order,
            picked,
            open_count,
            name,
            payment_status,
            paused,
            unpaid,
        ) in rows:
            if order.status == OrderStatus.ACTIVE:
                attention["active"] += 1
            queue, reasons = self._attention_reasons(
                now, order, picked, payment_status, paused, unpaid
            )
            if queue is None:
                continue
            attention[queue].append(
                {
                    "order_id": str(order.order_id),
                    "advertiser": name,
                    "offer_text": order.offer_text,
                    "created_at": order.created_at,
                    "age_hours": self._age_hours(now, order.created_at),
                    "picked_count": int(picked),
                    "needed_count": int(order.bloggers_needed),
                    "has_problem": open_count > 0,
                    "reasons": reasons,
                }
            )
        return attention

    def _attention_reasons(
        self,
        now: datetime,
        order: OrderModel,
        picked: int,
        payment_status: PaymentStatus | None,
        paused: bool | None,
        aging_unpaid: bool,
    ) -> tuple[str | None, list[str]]:
        if order.status == OrderStatus.PENDING_MODERATION or (
            order.status == OrderStatus.NEW
            and payment_status == PaymentStatus.PAID
        ):
            return "moderation", ["waiting_moderation"]
        if order.status == OrderStatus.NEW:
            if aging_unpaid:
                return "unpaid", ["waiting_payment"]
            return None, []
        if order.dispatch_stopped or picked >= order.bloggers_needed:
            return None, []
        if paused:
            return "delayed", ["dispatch_paused"]
        reasons = self._get_delay_reasons(now, order, picked)
        return ("delayed", reasons) if reasons else (None, [])

    def _apply_referrers_filter(
        self,
        referrers: list[dict],
        filter_by: str | None,
    ) -> list[dict]:
        """Filter referrers by activity or earnings in period."""
        if not referrers or not filter_by or filter_by == "all":
            return referrers
        if filter_by == "active_in_period":
            return [r for r in referrers if (r.get("new_in_period") or 0) > 0]
        if filter_by in ("top_by_earnings_period", "top_by_balance"):
            return [r for r in referrers if (r.get("balance") or 0) > 0]
        if filter_by == "top_by_referred":
            return referrers
        return referrers

    def _referrers_filter_default_sort(
        self, filter_by: str | None
    ) -> str | None:
        """Default sort key when a referrer filter is selected."""
        if filter_by == "top_by_referred":
            return "total_referred"
        if filter_by == "active_in_period":
            return "new_in_period"
        if filter_by in ("top_by_earnings_period", "top_by_balance"):
            return "balance"
        return None

    def _sort_referrers(
        self,
        referrers: list[dict],
        sort_by: str | None,
        order: str,
    ) -> list[dict]:
        """Sort referrers by given field (balance, total_referred, etc.)."""
        if not referrers or not sort_by:
            return referrers
        key_map = {
            "balance": lambda x: (
                x.get("balance") is None,
                x.get("balance") or 0,
            ),
            "total_referred": lambda x: x.get("total_referred", 0),
            "creators": lambda x: x.get("referred_creators", 0),
            "advertisers": lambda x: x.get("referred_advertisers", 0),
            "new_in_period": lambda x: x.get("new_in_period", 0),
            "manager": lambda x: (
                x.get("telegram") or x.get("username") or ""
            ).lower(),
            "code": lambda x: (x.get("referral_code") or "").lower(),
        }
        key_fn = key_map.get(sort_by)
        if key_fn is None:
            return referrers
        reverse = order != "asc"
        return sorted(
            referrers,
            key=lambda x: (key_fn(x), x.get("user_id", "")),
            reverse=reverse,
        )

    def _user_search_condition(self, search_query: str | None):
        """Return SQL condition for username/telegram/external_id search."""
        if not search_query:
            return None
        conditions: list[ColumnElement[bool]] = [
            UserModel.username.ilike(f"%{search_query}%"),
            UserModel.telegram.ilike(f"%{search_query}%"),
        ]
        with contextlib.suppress(ValueError, TypeError):
            conditions.append(UserModel.user_id == UUID(search_query))  # type: ignore[arg-type]
        if search_query.isdigit():
            conditions.append(UserModel.telegram_id == search_query)  # type: ignore[arg-type]
            conditions.append(UserModel.max_id == search_query)  # type: ignore[arg-type]
        return or_(*conditions)

    async def _count_creators(
        self,
        session: AsyncSession,
        window: PeriodWindow,
        only_new: bool,
        only_with_complaints: bool,
        search_query: str | None = None,
    ) -> int:
        """Count creators matching filters."""
        responses = (
            select(
                OfferDispatchModel.blogger_id.label("user_id"),
                func.count(OfferDispatchModel.blogger_id).label("responses"),
            )
            .where(OfferDispatchModel.accepted.isnot(None))
            .group_by(OfferDispatchModel.blogger_id)
            .subquery()
        )
        complaints = (
            select(
                ComplaintModel.reported_id.label("user_id"),
                func.count(ComplaintModel.complaint_id).label("complaints"),
            )
            .group_by(ComplaintModel.reported_id)
            .subquery()
        )
        query = (
            select(func.count(UserModel.user_id))
            .select_from(UserModel)
            .join(
                BloggerProfileModel,
                BloggerProfileModel.user_id == UserModel.user_id,
            )
            .outerjoin(responses, responses.c.user_id == UserModel.user_id)
            .outerjoin(complaints, complaints.c.user_id == UserModel.user_id)
        )
        if only_new:
            query = query.where(
                and_(
                    UserModel.created_at >= window.current_start,
                    UserModel.created_at < window.current_end,
                )
            )
        if only_with_complaints:
            query = query.where(func.coalesce(complaints.c.complaints, 0) > 0)
        search_cond = self._user_search_condition(search_query)
        if search_cond is not None:
            query = query.where(search_cond)
        result = await session.execute(query)
        return int(result.scalar() or 0)

    async def _list_creators(
        self,
        session: AsyncSession,
        window: PeriodWindow,
        only_new: bool,
        only_with_complaints: bool,
        limit: int = 25,
        offset: int = 0,
        search_query: str | None = None,
        sort_by: str = "created_at",
        order_asc: bool = False,
    ) -> list[dict]:
        """List creators with response and complaint counts."""
        responses = (
            select(
                OfferDispatchModel.blogger_id.label("user_id"),
                func.count(OfferDispatchModel.blogger_id).label("responses"),
            )
            .where(OfferDispatchModel.accepted.isnot(None))
            .group_by(OfferDispatchModel.blogger_id)
            .subquery()
        )
        complaints = (
            select(
                ComplaintModel.reported_id.label("user_id"),
                func.count(ComplaintModel.complaint_id).label("complaints"),
            )
            .group_by(ComplaintModel.reported_id)
            .subquery()
        )
        query = (
            select(
                UserModel,
                BloggerProfileModel.instagram_url,
                BloggerProfileModel.city,
                BloggerProfileModel.instagram_followers_count,
                func.coalesce(responses.c.responses, 0).label("responses"),
                func.coalesce(complaints.c.complaints, 0).label("complaints"),
            )
            .join(
                BloggerProfileModel,
                BloggerProfileModel.user_id == UserModel.user_id,
            )
            .outerjoin(responses, responses.c.user_id == UserModel.user_id)
            .outerjoin(complaints, complaints.c.user_id == UserModel.user_id)
        )
        if only_new:
            query = query.where(
                and_(
                    UserModel.created_at >= window.current_start,
                    UserModel.created_at < window.current_end,
                )
            )
        if only_with_complaints:
            query = query.where(func.coalesce(complaints.c.complaints, 0) > 0)
        search_cond = self._user_search_condition(search_query)
        if search_cond is not None:
            query = query.where(search_cond)
        order_column = self._creators_sort_column(
            sort_by, responses, complaints
        )
        if order_column is not None:
            direction = order_column.asc() if order_asc else order_column.desc()
            if sort_by in ("followers", "city"):
                direction = direction.nulls_last()
            query = query.order_by(direction)
        else:
            query = query.order_by(UserModel.created_at.desc())
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        rows = result.all()
        items = []
        for row in rows:
            (
                user,
                instagram_url,
                city,
                followers_count,
                resp_count,
                compl_count,
            ) = row
            items.append(
                {
                    "user_id": str(user.user_id),
                    "username": user.username,
                    "telegram": user.telegram,
                    "instagram": instagram_url,
                    "city": city or "",
                    "created_at": user.created_at,
                    "responses": int(resp_count),
                    "complaints": int(compl_count),
                    "status": self._user_status_label(user.status),
                    "instagram_followers_count": followers_count,
                }
            )
        return items

    def _creators_sort_column(self, sort_by: str, responses, complaints):
        """Return sort column for creators list or None for default."""
        if sort_by == "user_id":
            return UserModel.user_id
        if sort_by == "username":
            return UserModel.username
        if sort_by == "city":
            return BloggerProfileModel.city
        if sort_by == "created_at":
            return UserModel.created_at
        if sort_by == "followers":
            return BloggerProfileModel.instagram_followers_count
        if sort_by == "responses":
            return func.coalesce(responses.c.responses, 0)
        if sort_by == "complaints":
            return func.coalesce(complaints.c.complaints, 0)
        if sort_by == "status":
            return UserModel.status
        return None

    async def _count_advertisers(
        self,
        session: AsyncSession,
        search_query: str | None = None,
    ) -> int:
        """Count advertisers with profile."""
        query = (
            select(func.count(UserModel.user_id))
            .select_from(UserModel)
            .join(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == UserModel.user_id,
            )
        )
        search_cond = self._user_search_condition(search_query)
        if search_cond is not None:
            query = query.where(search_cond)
        result = await session.execute(query)
        return int(result.scalar() or 0)

    def _advertisers_sort_column(self, sort_by: str, orders, complaints):
        """Return sort column for advertisers list or None for default."""
        if sort_by == "user_id":
            return UserModel.user_id
        if sort_by == "created_at":
            return UserModel.created_at
        if sort_by == "name":
            return func.coalesce(
                AdvertiserProfileModel.brand, UserModel.username
            )
        if sort_by == "orders_total":
            return func.coalesce(orders.c.orders_total, 0)
        if sort_by == "last_order_at":
            return orders.c.last_order_at
        if sort_by == "orders_completed":
            return func.coalesce(orders.c.orders_completed, 0)
        if sort_by == "complaints":
            return func.coalesce(complaints.c.complaints, 0)
        return None

    async def _list_advertisers(
        self,
        session: AsyncSession,
        limit: int = 25,
        offset: int = 0,
        search_query: str | None = None,
        sort_by: str = "created_at",
        order_asc: bool = False,
    ) -> list[dict]:
        """List advertisers with order and complaint counts."""
        responses = self._order_responses_subquery()
        orders = (
            select(
                OrderModel.advertiser_id.label("advertiser_id"),
                func.count(OrderModel.order_id).label("orders_total"),
                func.max(OrderModel.created_at).label("last_order_at"),
                func.sum(
                    case(
                        (
                            self._completed_order_condition(responses),
                            1,
                        ),
                        else_=0,
                    )
                ).label("orders_completed"),
            )
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .where(*worklist_conditions("all", ""))
            .group_by(OrderModel.advertiser_id)
            .subquery()
        )
        complaints = (
            select(
                ComplaintModel.reported_id.label("user_id"),
                func.count(ComplaintModel.complaint_id).label("complaints"),
            )
            .group_by(ComplaintModel.reported_id)
            .subquery()
        )
        query = (
            select(
                UserModel,
                AdvertiserProfileModel.brand,
                func.coalesce(orders.c.orders_total, 0).label("orders_total"),
                func.coalesce(orders.c.orders_completed, 0).label(
                    "orders_completed"
                ),
                func.coalesce(complaints.c.complaints, 0).label("complaints"),
                orders.c.last_order_at,
            )
            .join(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == UserModel.user_id,
            )
            .outerjoin(orders, orders.c.advertiser_id == UserModel.user_id)
            .outerjoin(complaints, complaints.c.user_id == UserModel.user_id)
        )
        search_cond = self._user_search_condition(search_query)
        if search_cond is not None:
            query = query.where(search_cond)
        order_column = self._advertisers_sort_column(
            sort_by, orders, complaints
        )
        if order_column is not None:
            query = query.order_by(
                (
                    order_column.asc() if order_asc else order_column.desc()
                ).nulls_last()
            )
        else:
            query = query.order_by(UserModel.created_at.desc())
        query = query.order_by(UserModel.user_id).limit(limit).offset(offset)
        result = await session.execute(query)
        rows = result.all()
        payload: list[dict] = []
        for row in rows:
            (
                user,
                brand,
                orders_total,
                orders_completed,
                complaints_count,
                last_order_at,
            ) = row
            payload.append(
                {
                    "user_id": str(user.user_id),
                    "name": brand or user.username,
                    "telegram": user.telegram,
                    "created_at": user.created_at,
                    "orders_total": int(orders_total),
                    "orders_completed": int(orders_completed),
                    "last_order_at": last_order_at,
                    "complaints": int(complaints_count),
                }
            )
        return payload

    async def _count_orders(
        self,
        session: AsyncSession,
        window: PeriodWindow,
        status_filter: str | None,
        search: str | None = None,
    ) -> int:
        """Count orders in period matching status filter."""
        responses = self._order_responses_subquery()
        open_complaints = self._open_complaints_subquery()
        query = (
            select(func.count(OrderModel.order_id))
            .select_from(OrderModel)
            .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            )
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .outerjoin(
                open_complaints,
                open_complaints.c.order_id == OrderModel.order_id,
            )
            .where(
                *worklist_conditions("all", ""),
                and_(
                    OrderModel.created_at >= window.current_start,
                    OrderModel.created_at < window.current_end,
                ),
            )
        )
        status_cond = self._order_status_filter_condition(
            responses, open_complaints, status_filter
        )
        if status_cond is not None:
            query = query.where(status_cond)
        if search:
            query = query.where(self._order_search_condition(search))
        result = await session.execute(query)
        return int(result.scalar() or 0)

    async def _list_orders(
        self,
        session: AsyncSession,
        window: PeriodWindow,
        status_filter: str | None,
        limit: int = 25,
        offset: int = 0,
        sort_by: str = "created_at",
        order_asc: bool = False,
        search: str | None = None,
    ) -> list[dict]:
        """List orders with derived status labels and flags."""
        responses = self._order_responses_subquery()
        dispatched_subq = self._order_responses_total_subquery()
        accepted_subq = self._order_accepted_count_subquery()
        open_complaints = self._open_complaints_subquery()
        query = (
            select(
                OrderModel,
                func.coalesce(responses.c.responses, 0).label("responses"),
                func.coalesce(open_complaints.c.open_complaints, 0).label(
                    "open_complaints"
                ),
                func.coalesce(
                    AdvertiserProfileModel.brand, UserModel.username
                ).label("advertiser_name"),
                UserModel.telegram.label("advertiser_telegram"),
                func.coalesce(dispatched_subq.c.dispatched_count, 0).label(
                    "dispatched_count"
                ),
                func.coalesce(accepted_subq.c.accepted_count, 0).label(
                    "accepted_count"
                ),
            )
            .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            )
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .outerjoin(
                dispatched_subq,
                dispatched_subq.c.order_id == OrderModel.order_id,
            )
            .outerjoin(
                accepted_subq,
                accepted_subq.c.order_id == OrderModel.order_id,
            )
            .outerjoin(
                open_complaints,
                open_complaints.c.order_id == OrderModel.order_id,
            )
            .where(
                *worklist_conditions("all", ""),
                and_(
                    OrderModel.created_at >= window.current_start,
                    OrderModel.created_at < window.current_end,
                ),
            )
        )
        status_cond = self._order_status_filter_condition(
            responses, open_complaints, status_filter
        )
        if status_cond is not None:
            query = query.where(status_cond)
        if search:
            query = query.where(self._order_search_condition(search))
        sort_map: dict[str, Any] = {
            "order_id": OrderModel.order_id,
            "advertiser": func.coalesce(
                AdvertiserProfileModel.brand, UserModel.username
            ),
            "status": OrderModel.status,
            "picked_count": func.coalesce(responses.c.responses, 0),
            "responses": func.coalesce(responses.c.responses, 0),
            "dispatched_count": func.coalesce(
                dispatched_subq.c.dispatched_count, 0
            ),
            "open_complaints": func.coalesce(
                open_complaints.c.open_complaints, 0
            ),
            "status_age_hours": func.coalesce(
                OrderModel.completed_at, OrderModel.created_at
            ),
            "created_at": OrderModel.created_at,
        }
        order_col = sort_map.get(sort_by, OrderModel.created_at)
        query = query.order_by(
            order_col.asc() if order_asc else order_col.desc()
        )
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        rows = result.all()
        now = datetime.now(self._timezone)
        return [
            self._build_order_row(
                now,
                order,
                responses_count,
                open_count,
                name,
                advertiser_telegram=advertiser_telegram,
                dispatched_count=dispatched_count,
                accepted_count=accepted_count,
            )
            for (
                order,
                responses_count,
                open_count,
                name,
                advertiser_telegram,
                dispatched_count,
                accepted_count,
            ) in rows
        ]

    async def _get_order_card(
        self, session: AsyncSession, order_id: UUID
    ) -> dict | None:
        """Fetch detailed order card information."""
        responses = self._order_responses_subquery()
        dispatched_subq = self._order_responses_total_subquery()
        accepted_subq = self._order_accepted_count_subquery()
        open_complaints = self._open_complaints_subquery()
        query = (
            select(
                OrderModel,
                func.coalesce(responses.c.responses, 0).label("responses"),
                func.coalesce(open_complaints.c.open_complaints, 0).label(
                    "open_complaints"
                ),
                func.coalesce(
                    AdvertiserProfileModel.brand, UserModel.username
                ).label("advertiser_name"),
                func.coalesce(dispatched_subq.c.dispatched_count, 0).label(
                    "dispatched_count"
                ),
                func.coalesce(accepted_subq.c.accepted_count, 0).label(
                    "accepted_count"
                ),
            )
            .join(UserModel, UserModel.user_id == OrderModel.advertiser_id)
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == OrderModel.advertiser_id,
            )
            .outerjoin(responses, responses.c.order_id == OrderModel.order_id)
            .outerjoin(
                dispatched_subq,
                dispatched_subq.c.order_id == OrderModel.order_id,
            )
            .outerjoin(
                accepted_subq,
                accepted_subq.c.order_id == OrderModel.order_id,
            )
            .outerjoin(
                open_complaints,
                open_complaints.c.order_id == OrderModel.order_id,
            )
            .where(OrderModel.order_id == order_id)
        )
        result = await session.execute(query)
        row = result.one_or_none()
        if row is None:
            return None
        (
            order,
            responses_count,
            open_count,
            advertiser_name,
            dispatched_count,
            accepted_count,
        ) = row
        resp_list_result = await session.execute(
            select(OfferDispatchModel)
            .where(OfferDispatchModel.order_id == order_id)
            .order_by(
                OfferDispatchModel.updated_at.asc().nullslast(),
                OfferDispatchModel.created_at.asc(),
            )
        )
        response_models = resp_list_result.scalars().all()
        # Only creators who accepted or are in_offer (exclude "Пропустил")
        responses_list = [
            {
                "blogger_id": str(r.blogger_id),
                "responded_at": r.updated_at or r.created_at,
                "accepted": getattr(r, "accepted", None),
                "in_offer": getattr(r, "in_offer", True),
                "ugc_video_url": getattr(r, "ugc_video_url", None),
            }
            for r in response_models
            if r.accepted is not None
            and (getattr(r, "in_offer", True) or r.accepted is True)
        ]
        now = datetime.now(self._timezone)
        status_label = self._order_status_label(
            order, responses_count, open_count
        )
        card: dict[str, Any] = {
            "order_id": str(order.order_id),
            "advertiser_id": str(order.advertiser_id),
            "advertiser": advertiser_name,
            "order_type": order.order_type.value,
            "product_link": order.product_link,
            "offer_text": order.offer_text,
            "barter_description": getattr(order, "barter_description", None),
            "price": float(order.price),
            "currency": order.currency,
            "lifecycle_status": order.status.value,
            "bloggers_needed": int(order.bloggers_needed),
            "content_usage": getattr(order, "content_usage", None),
            "deadlines": getattr(order, "deadlines", None),
            "geography": getattr(order, "geography", None),
            "product_photo_file_id": getattr(
                order, "product_photo_file_id", None
            ),
            "min_followers": getattr(order, "min_followers", None),
            "max_followers": getattr(order, "max_followers", None),
            "min_age": getattr(order, "min_age", None),
            "max_age": getattr(order, "max_age", None),
            "min_publications": getattr(order, "min_publications", None),
            "max_publications": getattr(order, "max_publications", None),
            "required_blogger_gender": getattr(
                order, "required_blogger_gender", None
            ),
            "filter_by_price": getattr(order, "filter_by_price", False),
            "price_filter_delta": (
                float(order.price_filter_delta)
                if getattr(order, "price_filter_delta", None) is not None
                else None
            ),
            "filter_by_placement": getattr(order, "filter_by_placement", False),
            "filter_by_barter": getattr(order, "filter_by_barter", False),
            "picked_count": int(responses_count),
            "dispatched_count": int(dispatched_count),
            "accepted_count": int(accepted_count),
            "progress": self._progress_ratio(
                responses_count, order.bloggers_needed
            ),
            "created_at": order.created_at,
            "updated_at": getattr(order, "updated_at", None),
            "completed_at": order.completed_at,
            "status_label": status_label,
            "status_age_hours": self._status_age_hours(now, order),
            "has_problem": open_count > 0,
            "responses_list": responses_list,
            "description": order.offer_text,
        }
        if (
            order.status
            in (
                OrderStatus.NEW,
                OrderStatus.PENDING_MODERATION,
            )
            and self._offer_dispatch_service is not None
        ):
            try:
                card[
                    "eligible_creators_count"
                ] = await self._offer_dispatch_service.count_eligible_bloggers(
                    order.order_id, session=session
                )
            except Exception:  # noqa: S110
                card["eligible_creators_count"] = None
        else:
            card["eligible_creators_count"] = None
        return card

    async def _count_users_with_profile(
        self,
        session: AsyncSession,
        profile_model: type[Any],
        start: datetime,
        end: datetime,
    ) -> int:
        """Count users created in period with a matching profile."""
        query = (
            select(func.count(UserModel.user_id))
            .select_from(UserModel)
            .join(profile_model, profile_model.user_id == UserModel.user_id)
            .where(
                and_(UserModel.created_at >= start, UserModel.created_at < end)
            )
        )
        result = await session.execute(query)
        return int(result.scalar() or 0)

    def _build_delta(self, current: int, previous: int) -> dict:
        """Compute delta to previous period."""
        change_pct = (
            None if previous == 0 else (current - previous) / previous * 100
        )
        return {"count": current, "change_pct": change_pct}

    def _order_responses_subquery(self):
        """Build accepted (in_offer) count subquery per order."""
        return (
            select(
                OfferDispatchModel.order_id.label("order_id"),
                func.count(OfferDispatchModel.blogger_id).label("responses"),
            )
            .where(OfferDispatchModel.in_offer.is_(True))
            .group_by(OfferDispatchModel.order_id)
            .subquery()
        )

    def _order_responses_total_subquery(self):
        """Build total sent dispatches count subquery per order."""
        return (
            select(
                OfferDispatchModel.order_id.label("order_id"),
                func.count(OfferDispatchModel.blogger_id).label(
                    "dispatched_count"
                ),
            )
            .group_by(OfferDispatchModel.order_id)
            .subquery()
        )

    def _order_accepted_count_subquery(self):
        """Build accepted=True (responses) count subquery per order."""
        return (
            select(
                OfferDispatchModel.order_id.label("order_id"),
                func.count(OfferDispatchModel.blogger_id).label(
                    "accepted_count"
                ),
            )
            .where(OfferDispatchModel.accepted.is_(True))
            .group_by(OfferDispatchModel.order_id)
            .subquery()
        )

    def _open_complaints_subquery(self):
        """Build open complaints count subquery."""
        return (
            select(
                ComplaintModel.order_id.label("order_id"),
                func.sum(
                    case(
                        (
                            ComplaintModel.status.in_(OPEN_COMPLAINT_STATUSES),
                            1,
                        ),
                        else_=0,
                    )
                ).label("open_complaints"),
            )
            .group_by(ComplaintModel.order_id)
            .subquery()
        )

    def _completed_order_condition(
        self, responses_subquery
    ) -> ColumnElement[bool]:
        """Return SQL expression for completed orders."""
        return (OrderModel.status == OrderStatus.CLOSED) | (
            func.coalesce(responses_subquery.c.responses, 0)
            >= OrderModel.bloggers_needed
        )

    def _order_status_filter_condition(
        self,
        responses_subquery: Any,
        open_complaints_subquery: Any,
        status_filter: str | None,
    ) -> ColumnElement[bool] | None:
        """Return SQL condition for order status_filter."""
        if not status_filter:
            return None
        open_cnt = func.coalesce(open_complaints_subquery.c.open_complaints, 0)
        completed = self._completed_order_condition(responses_subquery)
        cutoff = datetime.now(self._timezone) - timedelta(
            days=self._thresholds.archive_days
        )
        if status_filter == "complaint":
            return open_cnt > 0
        if status_filter == "active":
            return and_(open_cnt == 0, ~completed)
        if status_filter == "archive":
            return and_(
                open_cnt == 0,
                completed,
                OrderModel.completed_at.isnot(None),
                OrderModel.completed_at < cutoff,
            )
        if status_filter == "completed":
            return and_(
                open_cnt == 0,
                completed,
                or_(
                    OrderModel.completed_at.is_(None),
                    OrderModel.completed_at >= cutoff,
                ),
            )
        return None

    @staticmethod
    def _order_search_condition(search: str) -> ColumnElement[bool]:
        """Return SQL condition for free-text order search."""
        escaped = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        like_pattern = f"%{escaped}%"
        conditions = [
            func.coalesce(
                AdvertiserProfileModel.brand, UserModel.username
            ).ilike(like_pattern),
            UserModel.username.ilike(like_pattern),
            UserModel.telegram.ilike(like_pattern),
            OrderModel.offer_text.ilike(like_pattern),
            OrderModel.barter_description.ilike(like_pattern),
            OrderModel.product_link.ilike(like_pattern),
            func.cast(OrderModel.order_id, String).ilike(like_pattern),
        ]
        return or_(*conditions)

    def _is_completed(self, order: OrderModel, responses: int) -> bool:
        """Return True when order is completed."""
        return bool(
            order.status == OrderStatus.CLOSED
            or int(responses) >= int(order.bloggers_needed)
        )

    def _is_archived(
        self, order: OrderModel, is_completed: bool, open_complaints: int
    ) -> bool:
        """Return True when order qualifies for archive."""
        if not is_completed or order.completed_at is None:
            return False
        if open_complaints > 0:
            return False
        cutoff = datetime.now(self._timezone) - timedelta(
            days=self._thresholds.archive_days
        )
        return order.completed_at < cutoff

    def _order_status_label(
        self, order: OrderModel, responses: int, open_complaints: int
    ) -> str:
        """Return derived order status label."""
        if open_complaints > 0:
            return "complaint"
        is_completed = self._is_completed(order, responses)
        if self._is_archived(order, is_completed, open_complaints):
            return "archive"
        if is_completed:
            return "completed"
        return "active"

    def _build_order_row(
        self,
        now: datetime,
        order: OrderModel,
        responses: int,
        open_complaints: int,
        advertiser_name: str,
        advertiser_telegram: str | None = None,
        dispatched_count: int = 0,
        accepted_count: int = 0,
    ) -> dict:
        """Build order list row for UI/API."""
        status_label = self._order_status_label(
            order, responses, open_complaints
        )
        return {
            "order_id": str(order.order_id),
            "advertiser_id": str(order.advertiser_id),
            "advertiser": advertiser_name,
            "offer_text": order.offer_text,
            "advertiser_telegram": advertiser_telegram,
            "status_label": status_label,
            "picked_count": int(responses),
            "needed_count": int(order.bloggers_needed),
            "dispatched_count": int(dispatched_count),
            "accepted_count": int(accepted_count),
            "created_at": order.created_at,
            "status_age_hours": self._status_age_hours(now, order),
            "has_problem": open_complaints > 0,
        }

    def _status_age_hours(self, now: datetime, order: OrderModel) -> float:
        """Return time spent in current status in hours."""
        reference = order.completed_at or order.created_at
        return self._age_hours(now, reference)

    def _progress_ratio(self, responses: int, needed: int) -> float:
        """Return progress ratio for order completion."""
        if needed <= 0:
            return 0.0
        return min(float(responses) / float(needed), 1.0)

    def _age_hours(self, now: datetime, created_at: datetime) -> float:
        """Return age in hours between now and created_at."""
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = now - created_at
        return round(delta.total_seconds() / 3600, 2)

    def _get_delay_reasons(
        self, now: datetime, order: OrderModel, responses: int
    ) -> list[str]:
        """Return delay reasons for an order."""
        reasons: list[str] = []
        age_hours = self._age_hours(now, order.created_at)
        if age_hours >= self._thresholds.active_days * 24:
            reasons.append("active_overdue")
        if responses == 0 and age_hours >= self._thresholds.no_responses_hours:
            reasons.append("no_responses")
        low_picked_target = min(3, int(order.bloggers_needed))
        if (
            responses < low_picked_target
            and age_hours >= self._thresholds.low_picked_hours
        ):
            reasons.append("low_picked")
        return reasons

    def _user_status_label(self, status: UserStatus) -> str:
        """Return human-readable user status label."""
        return "active" if status == UserStatus.ACTIVE else "limited"
