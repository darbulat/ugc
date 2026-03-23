"""SQLAlchemy referral repositories and income loader."""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, delete, func, select, union_all, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    PayoutRequestRepository,
    ReferralIncomeEntryRepository,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
)
from ugc_bot.domain.entities import (
    MissingReferralIncome,
    PayoutRequest,
    ReferralIncomeEntry,
    ReferralOrderIncomeRow,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import (
    InteractionStatus,
    OrderStatus,
    PaymentStatus,
    PayoutRequestStatus,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    PayoutRequestModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyUserReferralBindingRepository(UserReferralBindingRepository):
    """SQLAlchemy-backed user referral binding repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        binding: UserReferralBinding,
        session: object | None = None,
    ) -> None:
        """Persist referral binding."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = UserReferralBindingModel(
                referrer_user_id=binding.referrer_user_id,
                referred_user_id=binding.referred_user_id,
                created_at=binding.created_at,
            )
            await db_session.merge(model)

    async def get_by_referred_user(
        self, referred_user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralBinding]:
        """Fetch binding by referred user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserReferralBindingModel).where(
                    UserReferralBindingModel.referred_user_id
                    == referred_user_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_referral_binding_entity(result) if result else None

    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 10,
        session: object | None = None,
    ) -> Iterable[UserReferralBinding]:
        """List bindings by referrer user ID with pagination."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserReferralBindingModel)
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id
                )
                .order_by(UserReferralBindingModel.created_at)
                .offset(offset)
                .limit(limit)
            )
            return [
                _to_user_referral_binding_entity(m)
                for m in exec_result.scalars().all()
            ]

    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count bindings by referrer user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(UserReferralBindingModel)
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id
                )
            )
            return int(exec_result.scalar_one() or 0)


@dataclass(slots=True)
class SqlAlchemyUserReferralPendingRepository(UserReferralPendingRepository):
    """SQLAlchemy-backed user referral pending repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        pending: UserReferralPending,
        session: object | None = None,
    ) -> None:
        """Persist pending referral."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = UserReferralPendingModel(
                user_id=pending.user_id,
                referrer_user_id=pending.referrer_user_id,
                created_at=pending.created_at,
            )
            await db_session.merge(model)

    async def get_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[UserReferralPending]:
        """Fetch pending referral by user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserReferralPendingModel).where(
                    UserReferralPendingModel.user_id == user_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_user_referral_pending_entity(result) if result else None

    async def delete_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> None:
        """Delete pending referral by user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                delete(UserReferralPendingModel).where(
                    UserReferralPendingModel.user_id == user_id
                )
            )

    async def list_by_referrer(
        self,
        referrer_user_id: UUID,
        offset: int = 0,
        limit: int = 100,
        session: object | None = None,
    ) -> Iterable[UserReferralPending]:
        """List pending referrals by referrer user ID with pagination."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(UserReferralPendingModel)
                .where(
                    UserReferralPendingModel.referrer_user_id
                    == referrer_user_id
                )
                .order_by(UserReferralPendingModel.created_at)
                .offset(offset)
                .limit(limit)
            )
            return [
                _to_user_referral_pending_entity(m)
                for m in exec_result.scalars().all()
            ]

    async def count_by_referrer(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> int:
        """Count pending referrals by referrer user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(UserReferralPendingModel)
                .where(
                    UserReferralPendingModel.referrer_user_id
                    == referrer_user_id
                )
            )
            return int(exec_result.scalar_one() or 0)


@dataclass(slots=True)
class SqlAlchemyPayoutRequestRepository(PayoutRequestRepository):
    """SQLAlchemy-backed payout request repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        request: PayoutRequest,
        session: object | None = None,
    ) -> None:
        """Persist payout request."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_payout_request_model(request)
            db_session.add(model)

    async def get_by_id(
        self, request_id: UUID, session: object | None = None
    ) -> Optional[PayoutRequest]:
        """Fetch payout request by ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(PayoutRequestModel).where(
                    PayoutRequestModel.request_id == request_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_payout_request_entity(result) if result else None

    async def update_status(
        self,
        request_id: UUID,
        status: PayoutRequestStatus,
        session: object | None = None,
    ) -> bool:
        """Update payout request status. Returns True if row was updated."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                update(PayoutRequestModel)
                .where(PayoutRequestModel.request_id == request_id)
                .values(status=status)
            )
            return result.rowcount > 0  # type: ignore[attr-defined]

    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> Iterable[PayoutRequest]:
        """List payout requests by user ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(PayoutRequestModel).where(
                    PayoutRequestModel.user_id == user_id
                )
            )
            return [
                _to_payout_request_entity(m)
                for m in exec_result.scalars().all()
            ]

    async def list_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Iterable[PayoutRequest]:
        """List payout requests for given user IDs in one query."""
        if not user_ids:
            return []
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(PayoutRequestModel).where(
                    PayoutRequestModel.user_id.in_(user_ids)
                )
            )
            return [
                _to_payout_request_entity(m)
                for m in exec_result.scalars().all()
            ]

    async def get_paid_totals_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: sum_of_paid_amounts} for user."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    PayoutRequestModel.currency,
                    func.coalesce(func.sum(PayoutRequestModel.amount), 0),
                )
                .where(
                    PayoutRequestModel.user_id == user_id,
                    PayoutRequestModel.status == PayoutRequestStatus.PAID,
                )
                .group_by(PayoutRequestModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def get_pending_totals_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: sum_of_pending_amounts} for user."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    PayoutRequestModel.currency,
                    func.coalesce(func.sum(PayoutRequestModel.amount), 0),
                )
                .where(
                    PayoutRequestModel.user_id == user_id,
                    PayoutRequestModel.status == PayoutRequestStatus.PENDING,
                )
                .group_by(PayoutRequestModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def has_request_today_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, bool]:
        """Return {currency: True} for currencies with a request today."""
        from datetime import datetime, timezone

        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            stmt = (
                select(PayoutRequestModel.currency)
                .where(
                    PayoutRequestModel.user_id == user_id,
                    PayoutRequestModel.requested_at >= today_start,
                    PayoutRequestModel.status.notin_(
                        [
                            PayoutRequestStatus.CANCELLED,
                            PayoutRequestStatus.DELETED,
                        ]
                    ),
                )
                .group_by(PayoutRequestModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: True for row in result.all()}


@dataclass(slots=True)
class SqlAlchemyReferralIncomeEntryRepository(ReferralIncomeEntryRepository):
    """SQLAlchemy-backed referral income entry repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, entry: ReferralIncomeEntry, session: object | None = None
    ) -> None:
        """Save entry; skip if duplicate key."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                pg_insert(ReferralIncomeEntryModel)
                .values(
                    entry_id=entry.entry_id,
                    referrer_user_id=entry.referrer_user_id,
                    referred_user_id=entry.referred_user_id,
                    order_id=entry.order_id,
                    income_type=entry.income_type,
                    currency=entry.currency,
                    platform_revenue=entry.platform_revenue,
                    commission_rate=entry.commission_rate,
                    commission_amount=entry.commission_amount,
                    created_at=entry.created_at,
                )
                .on_conflict_do_nothing(
                    constraint="uq_referral_income_order_referrer_referred_type"
                )
            )
            await db_session.execute(stmt)

    async def exists(
        self,
        order_id: UUID,
        referrer_user_id: UUID,
        referred_user_id: UUID,
        income_type: str,
        session: object | None = None,
    ) -> bool:
        """Return True if entry exists for order+referrer+referred+type."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(func.count())
                .select_from(ReferralIncomeEntryModel)
                .where(
                    ReferralIncomeEntryModel.order_id == order_id,
                    ReferralIncomeEntryModel.referrer_user_id
                    == referrer_user_id,
                    ReferralIncomeEntryModel.referred_user_id
                    == referred_user_id,
                    ReferralIncomeEntryModel.income_type == income_type,
                )
                .limit(1)
            )
            result = await db_session.execute(stmt)
            return (result.scalar_one() or 0) > 0

    async def get_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: total_commission_amount} for referrer."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    ReferralIncomeEntryModel.currency,
                    func.sum(ReferralIncomeEntryModel.commission_amount),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id
                    == referrer_user_id
                )
                .group_by(ReferralIncomeEntryModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def get_orders_count_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, int]:
        """Return {currency: distinct_order_count} for referrer."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    ReferralIncomeEntryModel.currency,
                    func.count(
                        func.distinct(ReferralIncomeEntryModel.order_id)
                    ),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id
                    == referrer_user_id
                )
                .group_by(ReferralIncomeEntryModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: int(row[1]) for row in result.all()}

    async def get_current_month_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: total_commission_this_month} for referrer."""
        from datetime import datetime, timezone

        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            now = datetime.now(timezone.utc)
            first_day = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            stmt = (
                select(
                    ReferralIncomeEntryModel.currency,
                    func.sum(ReferralIncomeEntryModel.commission_amount),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id
                    == referrer_user_id,
                    ReferralIncomeEntryModel.created_at >= first_day,
                )
                .group_by(ReferralIncomeEntryModel.currency)
            )
            result = await db_session.execute(stmt)
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def get_batch_totals_by_referrer_ids(
        self,
        referrer_user_ids: list[UUID],
        session: object | None = None,
    ) -> dict[UUID, Decimal]:
        """Return {referrer_user_id: total_commission} for referrers."""
        if not referrer_user_ids:
            return {}
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    ReferralIncomeEntryModel.referrer_user_id,
                    func.sum(ReferralIncomeEntryModel.commission_amount),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id.in_(
                        referrer_user_ids
                    )
                )
                .group_by(ReferralIncomeEntryModel.referrer_user_id)
            )
            result = await db_session.execute(stmt)
            return {row[0]: Decimal(str(row[1])) for row in result.all()}

    async def find_missing_creator_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find creator orders with binding+CLOSED+PAID+OK, no entry."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    OrderModel.order_id,
                    InteractionModel.blogger_id.label("referred_user_id"),
                    func.coalesce(UserModel.country, "ru").label(
                        "advertiser_country_code"
                    ),
                )
                .select_from(InteractionModel)
                .join(
                    OrderModel, InteractionModel.order_id == OrderModel.order_id
                )
                .join(UserModel, OrderModel.advertiser_id == UserModel.user_id)
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserReferralBindingModel,
                    UserReferralBindingModel.referred_user_id
                    == InteractionModel.blogger_id,
                )
                .outerjoin(
                    ReferralIncomeEntryModel,
                    and_(
                        ReferralIncomeEntryModel.order_id
                        == OrderModel.order_id,
                        ReferralIncomeEntryModel.referrer_user_id
                        == UserReferralBindingModel.referrer_user_id,
                        ReferralIncomeEntryModel.income_type == "creator",
                    ),
                )
                .where(
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    InteractionModel.status == InteractionStatus.OK,
                    OrderModel.bloggers_needed > 0,
                    ReferralIncomeEntryModel.entry_id.is_(None),
                )
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            return [
                MissingReferralIncome(
                    order_id=row.order_id,
                    referred_user_id=row.referred_user_id,
                    advertiser_country_code=row.advertiser_country_code,
                    income_type="creator",
                )
                for row in result.all()
            ]

    async def find_missing_advertiser_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find advertiser orders with binding + CLOSED + PAID but no entry."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    OrderModel.order_id,
                    OrderModel.advertiser_id.label("referred_user_id"),
                    func.coalesce(UserModel.country, "ru").label(
                        "advertiser_country_code"
                    ),
                )
                .select_from(OrderModel)
                .join(UserModel, OrderModel.advertiser_id == UserModel.user_id)
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserReferralBindingModel,
                    UserReferralBindingModel.referred_user_id
                    == OrderModel.advertiser_id,
                )
                .outerjoin(
                    ReferralIncomeEntryModel,
                    and_(
                        ReferralIncomeEntryModel.order_id
                        == OrderModel.order_id,
                        ReferralIncomeEntryModel.referrer_user_id
                        == UserReferralBindingModel.referrer_user_id,
                        ReferralIncomeEntryModel.income_type == "advertiser",
                    ),
                )
                .where(
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    ReferralIncomeEntryModel.entry_id.is_(None),
                )
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            return [
                MissingReferralIncome(
                    order_id=row.order_id,
                    referred_user_id=row.referred_user_id,
                    advertiser_country_code=row.advertiser_country_code,
                    income_type="advertiser",
                )
                for row in result.all()
            ]


@dataclass(slots=True)
class SqlReferralOrderIncomeLoader:
    """Loads referral order income rows in one query to avoid N+1."""

    session_factory: async_sessionmaker[AsyncSession]

    async def load_referral_order_income_rows(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Return completed-order rows for referred creators (CLOSED, OK)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            query = (
                select(
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    OrderModel.bloggers_needed.label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OfferDispatchModel,
                    and_(
                        UserReferralBindingModel.referred_user_id
                        == OfferDispatchModel.blogger_id,
                        OfferDispatchModel.in_offer.is_(True),
                    ),
                )
                .join(
                    OrderModel,
                    OfferDispatchModel.order_id == OrderModel.order_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    InteractionModel,
                    and_(
                        InteractionModel.order_id == OrderModel.order_id,
                        InteractionModel.blogger_id
                        == UserReferralBindingModel.referred_user_id,
                        InteractionModel.advertiser_id
                        == OrderModel.advertiser_id,
                    ),
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id,
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    InteractionModel.status == InteractionStatus.OK,
                    OrderModel.bloggers_needed > 0,
                )
                .limit(limit)
            )
            result = await db_session.execute(query)
            rows = result.all()
            return [
                ReferralOrderIncomeRow(
                    creator_created_at=row.creator_created_at,
                    order_completed_at=row.order_completed_at,
                    payment_amount=float(row.payment_amount),
                    bloggers_needed=row.bloggers_needed,
                    order_id=row.order_id,
                )
                for row in rows
            ]

    async def load_referral_order_income_rows_advertisers(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Return rows for referred advertisers (CLOSED, PAID)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            query = (
                select(
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    func.coalesce(1).label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OrderModel,
                    OrderModel.advertiser_id
                    == UserReferralBindingModel.referred_user_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id,
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                )
                .limit(limit)
            )
            result = await db_session.execute(query)
            rows = result.all()
            return [
                ReferralOrderIncomeRow(
                    creator_created_at=row.creator_created_at,
                    order_completed_at=row.order_completed_at,
                    payment_amount=float(row.payment_amount),
                    bloggers_needed=1,
                    order_id=row.order_id,
                )
                for row in rows
            ]

    async def load_referral_order_income_rows_combined(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Blogger + advertiser rows in one query (UNION ALL, one LIMIT)."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            bloggers_query = (
                select(
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    OrderModel.bloggers_needed.label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OfferDispatchModel,
                    and_(
                        UserReferralBindingModel.referred_user_id
                        == OfferDispatchModel.blogger_id,
                        OfferDispatchModel.in_offer.is_(True),
                    ),
                )
                .join(
                    OrderModel,
                    OfferDispatchModel.order_id == OrderModel.order_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    InteractionModel,
                    and_(
                        InteractionModel.order_id == OrderModel.order_id,
                        InteractionModel.blogger_id
                        == UserReferralBindingModel.referred_user_id,
                        InteractionModel.advertiser_id
                        == OrderModel.advertiser_id,
                    ),
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id,
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    InteractionModel.status == InteractionStatus.OK,
                    OrderModel.bloggers_needed > 0,
                )
            )
            advertisers_query = (
                select(
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    func.coalesce(1).label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OrderModel,
                    OrderModel.advertiser_id
                    == UserReferralBindingModel.referred_user_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id
                    == referrer_user_id,
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                )
            )
            combined = union_all(bloggers_query, advertisers_query).subquery()
            stmt = (
                select(combined)
                .order_by(combined.c.order_completed_at.desc())
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            rows = result.all()
            return [
                ReferralOrderIncomeRow(
                    creator_created_at=row.creator_created_at,
                    order_completed_at=row.order_completed_at,
                    payment_amount=float(row.payment_amount),
                    bloggers_needed=row.bloggers_needed,
                    order_id=row.order_id,
                )
                for row in rows
            ]

    async def load_referral_order_income_rows_combined_batch(
        self,
        referrer_user_ids: List[UUID],
        limit: Optional[int] = None,
        session: object | None = None,
    ) -> List[Tuple[UUID, ReferralOrderIncomeRow]]:
        """Load income rows for multiple referrers in one query (UNION)."""
        if not referrer_user_ids:
            return []
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            effective_limit = limit if limit is not None else 100_000
            bloggers_query = (
                select(
                    UserReferralBindingModel.referrer_user_id.label(
                        "referrer_user_id"
                    ),
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    OrderModel.bloggers_needed.label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OfferDispatchModel,
                    and_(
                        UserReferralBindingModel.referred_user_id
                        == OfferDispatchModel.blogger_id,
                        OfferDispatchModel.in_offer.is_(True),
                    ),
                )
                .join(
                    OrderModel,
                    OfferDispatchModel.order_id == OrderModel.order_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    InteractionModel,
                    and_(
                        InteractionModel.order_id == OrderModel.order_id,
                        InteractionModel.blogger_id
                        == UserReferralBindingModel.referred_user_id,
                        InteractionModel.advertiser_id
                        == OrderModel.advertiser_id,
                    ),
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id.in_(
                        referrer_user_ids
                    ),
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    InteractionModel.status == InteractionStatus.OK,
                    OrderModel.bloggers_needed > 0,
                )
            )
            advertisers_query = (
                select(
                    UserReferralBindingModel.referrer_user_id.label(
                        "referrer_user_id"
                    ),
                    UserModel.created_at.label("creator_created_at"),
                    func.coalesce(
                        OrderModel.completed_at, OrderModel.created_at
                    ).label("order_completed_at"),
                    PaymentModel.amount.label("payment_amount"),
                    func.coalesce(1).label("bloggers_needed"),
                    OrderModel.order_id.label("order_id"),
                )
                .select_from(UserReferralBindingModel)
                .join(
                    OrderModel,
                    OrderModel.advertiser_id
                    == UserReferralBindingModel.referred_user_id,
                )
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserModel,
                    UserReferralBindingModel.referred_user_id
                    == UserModel.user_id,
                )
                .where(
                    UserReferralBindingModel.referrer_user_id.in_(
                        referrer_user_ids
                    ),
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                )
            )
            combined = union_all(bloggers_query, advertisers_query).subquery()
            stmt = select(combined).limit(effective_limit)
            result = await db_session.execute(stmt)
            rows = result.all()
            return [
                (
                    row.referrer_user_id,
                    ReferralOrderIncomeRow(
                        creator_created_at=row.creator_created_at,
                        order_completed_at=row.order_completed_at,
                        payment_amount=float(row.payment_amount),
                        bloggers_needed=row.bloggers_needed,
                        order_id=row.order_id,
                    ),
                )
                for row in rows
            ]


def _to_user_referral_binding_entity(
    model: UserReferralBindingModel,
) -> UserReferralBinding:
    """Map user referral binding ORM model to domain entity."""
    return UserReferralBinding(
        referrer_user_id=model.referrer_user_id,
        referred_user_id=model.referred_user_id,
        created_at=model.created_at,
    )


def _to_user_referral_pending_entity(
    model: UserReferralPendingModel,
) -> UserReferralPending:
    """Map user referral pending ORM model to domain entity."""
    return UserReferralPending(
        user_id=model.user_id,
        referrer_user_id=model.referrer_user_id,
        created_at=model.created_at,
    )


def _to_payout_request_entity(
    model: PayoutRequestModel,
) -> PayoutRequest:
    """Map payout request ORM model to domain entity."""
    return PayoutRequest(
        request_id=model.request_id,
        user_id=model.user_id,
        requested_at=model.requested_at,
        status=model.status,
        amount=model.amount,
        updated_at=model.updated_at,
        currency=model.currency,
    )


def _to_payout_request_model(request: PayoutRequest) -> PayoutRequestModel:
    """Map domain payout request entity to ORM model."""
    return PayoutRequestModel(
        request_id=request.request_id,
        user_id=request.user_id,
        requested_at=request.requested_at,
        status=request.status,
        amount=request.amount,
        updated_at=request.updated_at or request.requested_at,
        currency=request.currency,
    )
