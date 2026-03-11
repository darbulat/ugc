"""SQLAlchemy repository implementations."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
)
from typing import (
    cast as typing_cast,
)
from uuid import UUID

from geoalchemy2 import shape
from geoalchemy2.elements import WKBElement, WKTElement
from geoalchemy2.functions import ST_Intersects
from sqlalchemy import (
    String,
    and_,
    bindparam,
    cast,
    delete,
    func,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    BotTextsRepository,
    ComplaintRepository,
    ContactPricingRepository,
    CountryRepository,
    InstagramStatsRepository,
    InstagramVerificationRepository,
    InteractionRepository,
    NpsRepository,
    OfferDispatchRepository,
    OrderRepository,
    OutboxRepository,
    PaymentRepository,
    PayoutRequestRepository,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    ContactPricing,
    Country,
    InstagramStats,
    InstagramVerificationCode,
    Interaction,
    OfferDispatch,
    Order,
    OutboxEvent,
    Payment,
    PayoutRequest,
    ReferralOrderIncomeRow,
    User,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import (
    BloggerGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    PaymentStatus,
    PayoutRequestStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    BotTextModel,
    ComplaintModel,
    ContactPricingModel,
    CountryModel,
    InstagramStatsModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    PayoutRequestModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)

logger = logging.getLogger(__name__)


def _geometry_to_wkt(geom: object | None) -> Optional[str]:
    """Convert GeoAlchemy2 geometry column value to WKT string.

    Requires geoalchemy2[shapely] for WKBElement/WKTElement from PostgreSQL.
    """
    if geom is None:
        return None
    if isinstance(geom, str):
        return geom if geom.strip() else None
    try:
        return shape.to_shape(
            typing_cast(Union[WKBElement, WKTElement], geom)
        ).wkt
    except Exception as exc:
        logger.warning(
            "Failed to convert geometry to WKT",
            extra={"geom_type": type(geom).__name__, "error": str(exc)},
        )
        return None


def _wkt_to_geometry_element(
    wkt: Optional[str], srid: int = 4326
) -> object | None:
    """Convert WKT string to GeoAlchemy2 WKTElement for insert/update."""
    if not wkt or not wkt.strip():
        return None
    return WKTElement(wkt, srid=srid)


def _require_session(session: AsyncSession | None) -> AsyncSession:
    """Ensure an AsyncSession is provided.

    We keep `session: object | None` in repository ports to support in-memory
    repositories in unit tests. SQLAlchemy repositories must always operate
    with an explicit session provided by a higher-level transaction boundary
    (e.g., transaction manager).
    """

    if session is None:
        raise RuntimeError(
            "Database session is required. Use a transaction boundary and pass "
            "the session explicitly (e.g., via transaction manager)."
        )
    return session


def _get_async_session(session: object | None) -> AsyncSession:
    """Return a session-like object or raise with a clear error.

    We intentionally avoid strict `isinstance(..., AsyncSession)` checks to keep
    repository unit tests fast (they use lightweight fake sessions).
    """

    if session is None:
        return _require_session(None)
    # At runtime, we only require that the object behaves like an AsyncSession.
    return session  # type: ignore[return-value]


@dataclass(slots=True)
class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed user repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by ID."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        result = exec_result.scalar_one_or_none()
        return _to_user_entity(result) if result else None

    async def get_by_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, User]:
        """Fetch users by IDs in one query."""
        if not user_ids:
            return {}
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(UserModel.user_id.in_(user_ids))
        )
        rows = exec_result.scalars().all()
        return {row.user_id: _to_user_entity(row) for row in rows}

    async def get_by_external(
        self,
        external_id: str,
        messenger_type: MessengerType,
        session: object | None = None,
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(
                UserModel.external_id == external_id,
                UserModel.messenger_type == messenger_type.value,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_user_entity(result) if result else None

    async def get_by_referral_code(
        self, referral_code: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by referral code."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(
                UserModel.referral_code == referral_code,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_user_entity(result) if result else None

    async def get_by_telegram(
        self, telegram: str, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by Telegram username (case-insensitive, @ stripped)."""
        normalized = (telegram or "").strip().lstrip("@").lower()
        if not normalized:
            return None
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(
                func.lower(UserModel.telegram) == normalized,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_user_entity(result) if result else None

    async def save(self, user: User, session: object | None = None) -> None:
        """Persist a user."""

        db_session = _get_async_session(session)
        model = _to_user_model(user)
        await db_session.merge(model)

    async def list_pending_role_reminders(
        self, reminder_cutoff: datetime, session: object | None = None
    ) -> Iterable[User]:
        """List users who have not chosen a role and are due for a reminder."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserModel).where(
                UserModel.role_chosen_at.is_(None),
                (UserModel.last_role_reminder_at.is_(None))
                | (UserModel.last_role_reminder_at < reminder_cutoff),
            )
        )
        results = exec_result.scalars().all()
        return [_to_user_entity(row) for row in results]

    async def list_admins(
        self,
        messenger_type: MessengerType | None = None,
        session: object | None = None,
    ) -> Iterable[User]:
        """List users with admin=True. Optionally filter by messenger_type."""

        db_session = _get_async_session(session)
        query = select(UserModel).where(UserModel.admin.is_(True))
        if messenger_type is not None:
            query = query.where(
                UserModel.messenger_type == messenger_type.value
            )
        exec_result = await db_session.execute(query)
        results = exec_result.scalars().all()
        return [_to_user_entity(row) for row in results]


@dataclass(slots=True)
class SqlAlchemyBloggerProfileRepository(BloggerProfileRepository):
    """SQLAlchemy-backed blogger profile repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(BloggerProfileModel).where(
                BloggerProfileModel.user_id == user_id
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_blogger_profile_entity(result) if result else None

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, BloggerProfile]:
        """Fetch blogger profiles by user IDs in one query."""
        if not user_ids:
            return {}
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(BloggerProfileModel).where(
                BloggerProfileModel.user_id.in_(user_ids)
            )
        )
        rows = exec_result.scalars().all()
        return {row.user_id: _to_blogger_profile_entity(row) for row in rows}

    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(BloggerProfileModel).where(
                BloggerProfileModel.instagram_url == instagram_url
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_blogger_profile_entity(result) if result else None

    async def save(
        self, profile: BloggerProfile, session: object | None = None
    ) -> None:
        """Persist blogger profile."""

        db_session = _get_async_session(session)
        model = _to_blogger_profile_model(profile)
        await db_session.merge(model)

    async def list_confirmed_user_ids(
        self,
        session: object | None = None,
        location_geometry_wkt: Optional[str] = None,
    ) -> list[UUID]:
        """List confirmed blogger user ids.

        When location_geometry_wkt is set (PostgreSQL only), only return
        bloggers whose location_geometry intersects the order geometry.
        """
        db_session = _require_session(
            session if isinstance(session, AsyncSession) else None
        )
        stmt = select(BloggerProfileModel.user_id).where(
            BloggerProfileModel.confirmed.is_(True)
        )
        if location_geometry_wkt and location_geometry_wkt.strip():
            try:
                bind = db_session.sync_session.get_bind()
                if (
                    getattr(bind, "dialect", None)
                    and getattr(bind.dialect, "name", None) == "postgresql"
                ):
                    order_geom = WKTElement(
                        location_geometry_wkt.strip(), srid=4326
                    )
                    stmt = stmt.where(
                        BloggerProfileModel.location_geometry.isnot(None),
                        ST_Intersects(
                            BloggerProfileModel.location_geometry,
                            order_geom,
                        ),
                    )
            except AttributeError:
                pass
            except Exception as e:  # e.g. WKT parse error from GeoAlchemy2
                wkt_preview = (
                    (location_geometry_wkt or "")[:100]
                    if location_geometry_wkt
                    else ""
                )
                logger.warning(
                    "Invalid order location_geometry WKT, returning no "
                    "bloggers: %s",
                    e,
                    extra={"wkt_preview": wkt_preview},
                )
                return []
        exec_result = await db_session.execute(stmt)
        results = exec_result.scalars()
        return list(results)

    async def list_confirmed_with_instagram_id(
        self,
        limit: int,
        offset: int = 0,
        stats_older_than: Optional[datetime] = None,
        session: object | None = None,
    ) -> list[BloggerProfile]:
        """List confirmed profiles with non-empty instagram_user_id.

        When stats_older_than is set, only profiles with no instagram_stats
        row or instagram_stats.fetched_at < stats_older_than are returned.
        """
        db_session = _get_async_session(session)
        base_conditions = (
            BloggerProfileModel.confirmed.is_(True),
            BloggerProfileModel.instagram_user_id.isnot(None),
            BloggerProfileModel.instagram_user_id != "",
        )
        if stats_older_than is None:
            stmt = (
                select(BloggerProfileModel)
                .where(*base_conditions)
                .order_by(
                    BloggerProfileModel.instagram_stats_fetched_at.asc().nulls_first(),
                    BloggerProfileModel.user_id,
                )
                .limit(limit)
                .offset(offset)
            )
        else:
            stmt = (
                select(BloggerProfileModel)
                .outerjoin(
                    InstagramStatsModel,
                    BloggerProfileModel.user_id == InstagramStatsModel.user_id,
                )
                .where(
                    *base_conditions,
                    or_(
                        InstagramStatsModel.fetched_at.is_(None),
                        InstagramStatsModel.fetched_at < stats_older_than,
                    ),
                )
                .order_by(
                    InstagramStatsModel.fetched_at.asc().nulls_first(),
                    BloggerProfileModel.user_id,
                )
                .limit(limit)
                .offset(offset)
            )
        result = await db_session.execute(stmt)
        rows = result.scalars().all()
        return [_to_blogger_profile_entity(row) for row in rows]


@dataclass(slots=True)
class SqlAlchemyAdvertiserProfileRepository(AdvertiserProfileRepository):
    """SQLAlchemy-backed advertiser profile repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(AdvertiserProfileModel).where(
                AdvertiserProfileModel.user_id == user_id
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_advertiser_profile_entity(result) if result else None

    async def save(
        self, profile: AdvertiserProfile, session: object | None = None
    ) -> None:
        """Persist advertiser profile."""

        db_session = _get_async_session(session)
        model = _to_advertiser_profile_model(profile)
        await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyInstagramVerificationRepository(
    InstagramVerificationRepository
):
    """SQLAlchemy-backed Instagram verification repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code."""

        db_session = _get_async_session(session)
        model = _to_verification_model(code)
        await db_session.merge(model)

    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

        now = datetime.now(timezone.utc)
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InstagramVerificationCodeModel).where(
                InstagramVerificationCodeModel.user_id == user_id,
                InstagramVerificationCodeModel.code == code,
                InstagramVerificationCodeModel.used.is_(False),
                InstagramVerificationCodeModel.expires_at > now,
            )
        )
        result = exec_result.scalar_one_or_none()
        if result is None:
            return None
        if result.used or result.expires_at <= now:
            return None  # defensive: query already filters
        if result.code != code or result.user_id != user_id:
            return None
        return _to_verification_entity(result)

    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        """Mark verification code as used."""

        db_session = _get_async_session(session)
        model = await db_session.get(InstagramVerificationCodeModel, code_id)
        if model is None:
            return
        model.used = True

    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code by code string."""

        now = datetime.now(timezone.utc)
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InstagramVerificationCodeModel).where(
                InstagramVerificationCodeModel.code == code,
                InstagramVerificationCodeModel.used.is_(False),
                InstagramVerificationCodeModel.expires_at > now,
            )
        )
        result = exec_result.scalar_one_or_none()
        if result is None:
            return None
        if result.used or result.expires_at <= now:
            return None
        return _to_verification_entity(result)


@dataclass(slots=True)
class SqlAlchemyInstagramStatsRepository(InstagramStatsRepository):
    """SQLAlchemy-backed Instagram stats repository (Rapid API results)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[InstagramStats]:
        """Fetch Instagram stats by user id."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InstagramStatsModel).where(
                InstagramStatsModel.user_id == user_id
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_instagram_stats_entity(result) if result else None

    async def get_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, InstagramStats]:
        """Fetch Instagram stats by user IDs in one query."""
        if not user_ids:
            return {}
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InstagramStatsModel).where(
                InstagramStatsModel.user_id.in_(user_ids)
            )
        )
        rows = exec_result.scalars().all()
        return {row.user_id: _to_instagram_stats_entity(row) for row in rows}

    async def save(
        self, stats: InstagramStats, session: object | None = None
    ) -> None:
        """Persist or update Instagram stats (upsert by user_id)."""
        db_session = _get_async_session(session)
        model = _to_instagram_stats_model(stats)
        await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyOrderRepository(OrderRepository):
    """SQLAlchemy-backed order repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderModel).where(OrderModel.order_id == order_id)
        )
        result = exec_result.scalar_one_or_none()
        return _to_order_entity(result) if result else None

    async def get_by_id_for_update(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID with row lock."""

        stmt = (
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
        )
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(stmt)
        result = exec_result.scalar_one_or_none()
        return _to_order_entity(result) if result else None

    async def list_active(
        self, session: object | None = None
    ) -> Iterable[Order]:
        """List active orders."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderModel).where(OrderModel.status == OrderStatus.ACTIVE)
        )
        result = exec_result.scalars()
        return [_to_order_entity(item) for item in result]

    async def list_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> Iterable[Order]:
        """List orders by advertiser."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderModel).where(OrderModel.advertiser_id == advertiser_id)
        )
        result = exec_result.scalars()
        return [_to_order_entity(item) for item in result]

    async def list_completed_before(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Order]:
        """List orders completed before cutoff."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderModel).where(
                OrderModel.completed_at.is_not(None),
                OrderModel.completed_at <= cutoff,
            )
        )
        result = exec_result.scalars()
        return [_to_order_entity(item) for item in result]

    async def count_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> int:
        """Count orders by advertiser."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OrderModel)
            .where(OrderModel.advertiser_id == advertiser_id)
        )
        result = exec_result.scalar_one()
        return int(result)

    async def save(self, order: Order, session: object | None = None) -> None:
        """Persist order."""

        model = _to_order_model(order)
        db_session = _get_async_session(session)
        await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyPaymentRepository(PaymentRepository):
    """SQLAlchemy-backed payment repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by order id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(PaymentModel).where(PaymentModel.order_id == order_id)
        )
        result = exec_result.scalar_one_or_none()
        return _to_payment_entity(result) if result else None

    async def get_by_external_id(
        self, external_id: str, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by provider external id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(PaymentModel).where(PaymentModel.external_id == external_id)
        )
        result = exec_result.scalar_one_or_none()
        return _to_payment_entity(result) if result else None

    async def save(
        self, payment: Payment, session: object | None = None
    ) -> None:
        """Persist payment."""

        model = _to_payment_model(payment)
        db_session = _get_async_session(session)
        await db_session.merge(model)


@dataclass(slots=True)
class SqlAlchemyContactPricingRepository(ContactPricingRepository):
    """SQLAlchemy-backed contact pricing repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_bloggers_count(
        self, bloggers_count: int, session: object | None = None
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(ContactPricingModel).where(
                ContactPricingModel.bloggers_count == bloggers_count
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_contact_pricing_entity(result) if result else None


@dataclass(slots=True)
class SqlAlchemyBotTextsRepository(BotTextsRepository):
    """SQLAlchemy-backed bot texts repository (key, locale -> value)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get(
        self, key: str, locale: str, session: object | None = None
    ) -> Optional[str]:
        """Fetch text value for key and locale."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(BotTextModel).where(
                and_(
                    BotTextModel.key == key,
                    BotTextModel.locale == locale,
                )
            )
        )
        row = exec_result.scalar_one_or_none()
        return row.value if row else None

    async def get_all(
        self, session: object | None = None
    ) -> list[tuple[str, str, str]]:
        """Fetch all bot_texts rows as (key, locale, value)."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(select(BotTextModel))
        rows = exec_result.scalars().all()
        return [(r.key, r.locale, r.value) for r in rows]


@dataclass(slots=True)
class SqlAlchemyOfferDispatchRepository(OfferDispatchRepository):
    """SQLAlchemy-backed offer dispatch repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def record_sent(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> None:
        """Record that an offer was sent to a blogger for an order."""
        db_session = _get_async_session(session)
        model = OfferDispatchModel(
            order_id=order_id,
            blogger_id=blogger_id,
            in_offer=False,
        )
        await db_session.merge(model)

    async def record_response(
        self,
        order_id: UUID,
        blogger_id: UUID,
        accepted: bool,
        in_offer: bool,
        session: object | None = None,
    ) -> None:
        """Update dispatch with response (accepted/in_offer) and updated_at."""
        db_session = _get_async_session(session)
        now = datetime.now(timezone.utc)
        await db_session.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .values(accepted=accepted, in_offer=in_offer, updated_at=now)
        )

    async def list_blogger_ids_sent_for_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[UUID]:
        """List blogger ids who already received an offer for this order."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OfferDispatchModel.blogger_id).where(
                OfferDispatchModel.order_id == order_id
            )
        )
        return list(exec_result.scalars().all())

    async def list_responses_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> List[OfferDispatch]:
        """List dispatches (with response) by order."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OfferDispatchModel)
            .where(OfferDispatchModel.order_id == order_id)
            .order_by(
                OfferDispatchModel.updated_at.asc().nullslast(),
                OfferDispatchModel.created_at.asc(),
            )
        )
        results = exec_result.scalars().all()
        return [_to_offer_dispatch_entity(m) for m in results]

    async def list_responses_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> List[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null)."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OfferDispatchModel)
            .where(
                OfferDispatchModel.blogger_id == blogger_id,
                OfferDispatchModel.accepted.isnot(None),
            )
            .order_by(
                OfferDispatchModel.updated_at.desc().nullslast(),
                OfferDispatchModel.created_at.desc(),
            )
        )
        results = exec_result.scalars().all()
        return [_to_offer_dispatch_entity(m) for m in results]

    async def exists_responded(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded (accepted is not null)."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
                OfferDispatchModel.accepted.isnot(None),
            )
        )
        result = exec_result.scalar_one()
        return int(result) > 0

    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count dispatches by order (all rows)."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OfferDispatchModel)
            .where(OfferDispatchModel.order_id == order_id)
        )
        result = exec_result.scalar_one()
        return int(result)

    async def count_accepted_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count in_offer=true by order (accepted within limit)."""
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.in_offer.is_(True),
            )
        )
        result = exec_result.scalar_one()
        return int(result)

    async def count_completed_orders_by_blogger_ids(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        """Count completed orders (CLOSED, interaction OK) per blogger ID."""
        if not blogger_ids:
            return {}
        db_session = _get_async_session(session)
        query = (
            select(
                OfferDispatchModel.blogger_id,
                func.count().label("cnt"),
            )
            .select_from(OfferDispatchModel)
            .join(
                OrderModel,
                and_(
                    OfferDispatchModel.order_id == OrderModel.order_id,
                    OrderModel.status == OrderStatus.CLOSED,
                ),
            )
            .join(
                InteractionModel,
                and_(
                    InteractionModel.order_id == OfferDispatchModel.order_id,
                    InteractionModel.blogger_id
                    == OfferDispatchModel.blogger_id,
                    InteractionModel.advertiser_id == OrderModel.advertiser_id,
                    InteractionModel.status == InteractionStatus.OK,
                ),
            )
            .where(
                OfferDispatchModel.blogger_id.in_(blogger_ids),
                OfferDispatchModel.in_offer.is_(True),
            )
            .group_by(OfferDispatchModel.blogger_id)
        )
        exec_result = await db_session.execute(query)
        rows = exec_result.all()
        result = {uid: 0 for uid in blogger_ids}
        for row in rows:
            result[row.blogger_id] = int(row.cnt)
        return result


@dataclass(slots=True)
class SqlAlchemyInteractionRepository(InteractionRepository):
    """SQLAlchemy-backed interaction repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[Interaction]:
        """Fetch interaction by id."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.interaction_id == interaction_id
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_interaction_entity(result) if result else None

    async def get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        session: object | None = None,
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.order_id == order_id,
                InteractionModel.blogger_id == blogger_id,
                InteractionModel.advertiser_id == advertiser_id,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_interaction_entity(result) if result else None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions for order."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.order_id == order_id
            )
        )
        results = exec_result.scalars()
        return [_to_interaction_entity(item) for item in results]

    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback."""

        db_session = _get_async_session(session)
        status_param = cast(
            bindparam(
                "status_1",
                value=InteractionStatus.PENDING.value,
                type_=String(),
            ),
            InteractionModel.status.type,
        )
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.next_check_at <= cutoff,
                InteractionModel.status == status_param,
            )
        )
        results = exec_result.scalars()
        return [_to_interaction_entity(item) for item in results]

    async def list_by_status(
        self, status: InteractionStatus, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""

        db_session = _get_async_session(session)
        status_param = cast(
            bindparam(
                "status_1",
                value=status.value,
                type_=String(),
            ),
            InteractionModel.status.type,
        )
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.status == status_param
            )
        )
        results = exec_result.scalars()
        return [_to_interaction_entity(item) for item in results]

    async def save(
        self, interaction: Interaction, session: object | None = None
    ) -> None:
        """Persist interaction."""

        db_session = _get_async_session(session)
        model = _to_interaction_model(interaction)
        await db_session.merge(model)

    async def update_next_check_at(
        self,
        interaction_id: UUID,
        next_check_at: datetime,
        session: object | None = None,
    ) -> None:
        """Update next_check_at for an interaction."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(InteractionModel)
            .where(InteractionModel.interaction_id == interaction_id)
            .values(next_check_at=next_check_at)
        )

    async def list_blogger_ids_with_unfulfilled_interaction(
        self, session: object | None = None
    ) -> list[UUID]:
        """Blogger ids with at least one interaction PENDING or ISSUE."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel.blogger_id)
            .where(
                InteractionModel.status.in_(
                    [InteractionStatus.PENDING, InteractionStatus.ISSUE]
                )
            )
            .distinct()
        )
        return list(exec_result.scalars().all())


@dataclass(slots=True)
class SqlAlchemyNpsRepository(NpsRepository):
    """SQLAlchemy-backed NPS repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        user_id: UUID,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> None:
        """Save NPS score for a user."""

        db_session = _get_async_session(session)
        model = NpsResponseModel(
            user_id=user_id,
            score=score,
            comment=comment,
        )
        db_session.add(model)

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(NpsResponseModel)
            .where(NpsResponseModel.user_id == user_id)
        )
        count = exec_result.scalar_one()
        return int(count) > 0


def _to_user_entity(model: UserModel) -> User:
    """Map user ORM model to domain entity."""

    return User(
        user_id=model.user_id,
        external_id=model.external_id,
        messenger_type=model.messenger_type,
        username=model.username,
        status=model.status,
        issue_count=model.issue_count,
        created_at=model.created_at,
        role_chosen_at=model.role_chosen_at,
        last_role_reminder_at=model.last_role_reminder_at,
        telegram=getattr(model, "telegram", None),
        admin=getattr(model, "admin", False),
        referral_code=getattr(model, "referral_code", None),
        referral_payout_rate=getattr(model, "referral_payout_rate", None),
        agreement_confirmed_at=getattr(model, "agreement_confirmed_at", None),
        updated_at=getattr(model, "updated_at", None),
        country=getattr(model, "country", None),
    )


def _to_user_model(user: User) -> UserModel:
    """Map domain user entity to ORM model."""

    return UserModel(
        user_id=user.user_id,
        external_id=user.external_id,
        messenger_type=user.messenger_type,
        username=user.username,
        status=user.status,
        issue_count=user.issue_count,
        created_at=user.created_at,
        role_chosen_at=user.role_chosen_at,
        last_role_reminder_at=user.last_role_reminder_at,
        telegram=user.telegram,
        admin=getattr(user, "admin", False),
        referral_code=getattr(user, "referral_code", None),
        referral_payout_rate=getattr(user, "referral_payout_rate", None),
        agreement_confirmed_at=getattr(user, "agreement_confirmed_at", None),
        updated_at=getattr(user, "updated_at", None)
        or datetime.now(timezone.utc),
        country=getattr(user, "country", None),
    )


def _to_blogger_profile_entity(
    model: BloggerProfileModel,
) -> BloggerProfile:
    """Map blogger profile ORM model to domain entity."""

    work_format = model.work_format
    if isinstance(work_format, str):
        work_format = WorkFormat(work_format)
    blogger_gender = getattr(model, "blogger_gender", None)
    if blogger_gender is not None and isinstance(blogger_gender, str):
        blogger_gender = BloggerGender(blogger_gender)
    return BloggerProfile(
        user_id=model.user_id,
        instagram_url=model.instagram_url,
        confirmed=model.confirmed,
        city=model.city,
        topics=model.topics,
        audience_gender=model.audience_gender,
        audience_age_min=model.audience_age_min,
        audience_age_max=model.audience_age_max,
        audience_geo=model.audience_geo,
        price=float(model.price),
        barter=model.barter,
        work_format=work_format,
        wanted_to_change_terms_count=getattr(
            model, "wanted_to_change_terms_count", 0
        ),
        created_at=getattr(model, "created_at", model.updated_at),
        updated_at=model.updated_at,
        blogger_gender=blogger_gender,
        instagram_user_id=getattr(model, "instagram_user_id", None),
        instagram_followers_count=getattr(
            model, "instagram_followers_count", None
        ),
        instagram_username=getattr(model, "instagram_username", None),
        instagram_stats_fetched_at=getattr(
            model, "instagram_stats_fetched_at", None
        ),
        birth_date=getattr(model, "birth_date", None),
        region=getattr(model, "region", None),
        location_geometry=_geometry_to_wkt(
            getattr(model, "location_geometry", None)
        ),
        country=getattr(model, "country", ""),
        currency=getattr(model, "currency", "RUB"),
    )


def _to_blogger_profile_model(
    profile: BloggerProfile,
) -> BloggerProfileModel:
    """Map domain blogger profile entity to ORM model."""

    return BloggerProfileModel(
        user_id=profile.user_id,
        instagram_url=profile.instagram_url,
        confirmed=profile.confirmed,
        city=profile.city,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
        barter=profile.barter,
        work_format=profile.work_format,
        wanted_to_change_terms_count=profile.wanted_to_change_terms_count,
        created_at=profile.created_at or profile.updated_at,
        updated_at=profile.updated_at,
        blogger_gender=profile.blogger_gender,
        instagram_user_id=profile.instagram_user_id,
        instagram_followers_count=profile.instagram_followers_count,
        instagram_username=profile.instagram_username,
        instagram_stats_fetched_at=profile.instagram_stats_fetched_at,
        birth_date=profile.birth_date,
        region=profile.region,
        location_geometry=_wkt_to_geometry_element(profile.location_geometry),
        country=profile.country,
        currency=getattr(profile, "currency", "RUB"),
    )


def _to_interaction_entity(model: InteractionModel) -> Interaction:
    """Map interaction ORM model to domain entity."""

    return Interaction(
        interaction_id=model.interaction_id,
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        advertiser_id=model.advertiser_id,
        status=model.status,
        from_advertiser=model.from_advertiser,
        from_blogger=model.from_blogger,
        postpone_count=model.postpone_count,
        next_check_at=model.next_check_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_interaction_model(interaction: Interaction) -> InteractionModel:
    """Map domain interaction to ORM model."""

    return InteractionModel(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=interaction.status,
        from_advertiser=interaction.from_advertiser,
        from_blogger=interaction.from_blogger,
        postpone_count=interaction.postpone_count,
        next_check_at=interaction.next_check_at,
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )


def _to_advertiser_profile_entity(
    model: AdvertiserProfileModel,
) -> AdvertiserProfile:
    """Map advertiser profile ORM model to domain entity."""

    return AdvertiserProfile(
        user_id=model.user_id,
        phone=model.contact,
        brand=model.brand or "",
        site_link=getattr(model, "site_link", None),
        city=getattr(model, "city", None),
        company_activity=getattr(model, "company_activity", None),
        created_at=getattr(model, "created_at", None)
        or getattr(model, "updated_at", None),
        updated_at=getattr(model, "updated_at", None),
    )


def _to_advertiser_profile_model(
    profile: AdvertiserProfile,
) -> AdvertiserProfileModel:
    """Map domain advertiser profile entity to ORM model."""

    return AdvertiserProfileModel(
        user_id=profile.user_id,
        contact=profile.phone,
        brand=profile.brand or None,
        site_link=profile.site_link,
        city=profile.city,
        company_activity=profile.company_activity,
        created_at=profile.created_at or datetime.now(timezone.utc),
        updated_at=profile.updated_at or datetime.now(timezone.utc),
    )


def _to_verification_entity(
    model: InstagramVerificationCodeModel,
) -> InstagramVerificationCode:
    """Map verification ORM model to domain entity."""

    return InstagramVerificationCode(
        code_id=model.code_id,
        user_id=model.user_id,
        code=model.code,
        expires_at=model.expires_at,
        used=model.used,
        created_at=model.created_at,
    )


def _to_verification_model(
    code: InstagramVerificationCode,
) -> InstagramVerificationCodeModel:
    """Map domain verification entity to ORM model."""

    return InstagramVerificationCodeModel(
        code_id=code.code_id,
        user_id=code.user_id,
        code=code.code,
        expires_at=code.expires_at,
        used=code.used,
        created_at=code.created_at,
    )


def _to_instagram_stats_entity(model: InstagramStatsModel) -> InstagramStats:
    """Map Instagram stats ORM model to domain entity."""
    return InstagramStats(
        user_id=model.user_id,
        raw_response=model.raw_response,
        fetched_at=model.fetched_at,
        followers_count=model.followers_count,
        follows_count=model.follows_count,
        media_count=model.media_count,
        instagram_username=model.instagram_username,
        biography=model.biography,
        provider=model.provider,
        instagram_id=model.instagram_id,
    )


def _to_instagram_stats_model(stats: InstagramStats) -> InstagramStatsModel:
    """Map domain Instagram stats entity to ORM model."""
    return InstagramStatsModel(
        user_id=stats.user_id,
        raw_response=stats.raw_response,
        fetched_at=stats.fetched_at,
        followers_count=stats.followers_count,
        follows_count=stats.follows_count,
        media_count=stats.media_count,
        instagram_username=stats.instagram_username,
        biography=stats.biography,
        provider=stats.provider,
        instagram_id=stats.instagram_id,
    )


def _to_order_entity(model: OrderModel) -> Order:
    """Map order ORM model to domain entity."""

    return Order(
        order_id=model.order_id,
        advertiser_id=model.advertiser_id,
        order_type=getattr(model, "order_type", None) or OrderType.UGC_ONLY,
        product_link=model.product_link,
        offer_text=model.offer_text,
        barter_description=model.barter_description,
        price=float(model.price),
        bloggers_needed=model.bloggers_needed,
        status=model.status,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", model.created_at),
        completed_at=model.completed_at,
        content_usage=getattr(model, "content_usage", None),
        deadlines=getattr(model, "deadlines", None),
        geography=getattr(model, "geography", None),
        product_photo_file_id=getattr(model, "product_photo_file_id", None),
        min_followers=getattr(model, "min_followers", None),
        max_followers=getattr(model, "max_followers", None),
        min_age=getattr(model, "min_age", None),
        max_age=getattr(model, "max_age", None),
        min_publications=getattr(model, "min_publications", None),
        max_publications=getattr(model, "max_publications", None),
        required_blogger_gender=getattr(model, "required_blogger_gender", None),
        filter_by_price=getattr(model, "filter_by_price", False),
        price_filter_delta=(
            float(val)
            if (val := getattr(model, "price_filter_delta", None)) is not None
            else None
        ),
        filter_by_placement=getattr(model, "filter_by_placement", False),
        filter_by_barter=getattr(model, "filter_by_barter", False),
        location_geometry=_geometry_to_wkt(
            getattr(model, "location_geometry", None)
        ),
        currency=getattr(model, "currency", "RUB"),
    )


def _to_offer_dispatch_entity(model: OfferDispatchModel) -> OfferDispatch:
    """Map offer dispatch ORM model to domain entity."""

    return OfferDispatch(
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", None),
        accepted=getattr(model, "accepted", None),
        in_offer=getattr(model, "in_offer", True),
    )


def _to_order_model(order: Order) -> OrderModel:
    """Map domain order entity to ORM model."""

    return OrderModel(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=order.status,
        created_at=order.created_at,
        updated_at=order.updated_at or order.created_at,
        completed_at=order.completed_at,
        content_usage=order.content_usage,
        deadlines=order.deadlines,
        geography=order.geography,
        product_photo_file_id=order.product_photo_file_id,
        min_followers=order.min_followers,
        max_followers=order.max_followers,
        min_age=order.min_age,
        max_age=order.max_age,
        min_publications=order.min_publications,
        max_publications=order.max_publications,
        required_blogger_gender=order.required_blogger_gender,
        filter_by_price=order.filter_by_price,
        price_filter_delta=order.price_filter_delta,
        filter_by_placement=order.filter_by_placement,
        filter_by_barter=order.filter_by_barter,
        location_geometry=_wkt_to_geometry_element(order.location_geometry),
        currency=getattr(order, "currency", "RUB"),
    )


def _to_payment_entity(model: PaymentModel) -> Payment:
    """Map payment ORM model to domain entity."""

    return Payment(
        payment_id=model.payment_id,
        order_id=model.order_id,
        provider=model.provider,
        status=model.status,
        amount=float(model.amount),
        currency=model.currency,
        external_id=model.external_id,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", model.created_at),
        paid_at=model.paid_at,
    )


def _to_payment_model(payment: Payment) -> PaymentModel:
    """Map domain payment entity to ORM model."""

    return PaymentModel(
        payment_id=payment.payment_id,
        order_id=payment.order_id,
        provider=payment.provider,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        external_id=payment.external_id,
        created_at=payment.created_at,
        updated_at=payment.updated_at or payment.created_at,
        paid_at=payment.paid_at,
    )


def _to_contact_pricing_entity(model: ContactPricingModel) -> ContactPricing:
    """Map contact pricing ORM model to entity."""

    return ContactPricing(
        bloggers_count=model.bloggers_count,
        price=float(model.price),
        created_at=getattr(model, "created_at", model.updated_at),
        updated_at=model.updated_at,
    )


class SqlAlchemyOutboxRepository(OutboxRepository):
    """SQLAlchemy implementation of outbox repository."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save(
        self, event: OutboxEvent, session: object | None = None
    ) -> None:
        """Persist outbox event."""

        model = _to_outbox_event_model(event)
        db_session = _get_async_session(session)
        db_session.add(model)

    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Get pending events for processing."""

        db_session = _get_async_session(session)
        result = await db_session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.status == OutboxEventStatus.PENDING)
            .order_by(OutboxEventModel.created_at)
            .limit(limit)
        )
        models = result.scalars().all()
        return [_to_outbox_event_entity(model) for model in models]

    async def claim_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Claim pending events (set to PROCESSING) and return them."""

        db_session = _get_async_session(session)
        result = await db_session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.status == OutboxEventStatus.PENDING)
            .order_by(OutboxEventModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        models = result.scalars().all()
        if models:
            event_ids = [m.event_id for m in models]
            await db_session.execute(
                update(OutboxEventModel)
                .where(OutboxEventModel.event_id.in_(event_ids))
                .values(
                    status=OutboxEventStatus.PROCESSING,
                    claimed_at=datetime.now(timezone.utc),
                )
            )
        return [_to_outbox_event_entity(model) for model in models]

    async def mark_as_processing(
        self, event_id: UUID, session: object | None = None
    ) -> None:
        """Mark event as processing."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(status=OutboxEventStatus.PROCESSING)
        )

    async def mark_as_published(
        self,
        event_id: UUID,
        processed_at: datetime,
        session: object | None = None,
    ) -> None:
        """Mark event as published."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=OutboxEventStatus.PUBLISHED, processed_at=processed_at
            )
        )

    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed (terminal state)."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=OutboxEventStatus.FAILED,
                last_error=error,
                retry_count=retry_count,
            )
        )

    async def mark_for_retry(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Reset event to PENDING for retry."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(
                status=OutboxEventStatus.PENDING,
                last_error=error,
                retry_count=retry_count,
            )
        )

    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.event_id == event_id
            )
        )
        model = exec_result.scalar_one_or_none()
        return _to_outbox_event_entity(model) if model else None

    async def delete_processed_events(
        self,
        retention_days: int,
        batch_size: int,
        session: object | None = None,
    ) -> int:
        """Delete PUBLISHED/FAILED events older than retention_days."""

        if retention_days <= 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        db_session = _get_async_session(session)

        subq = (
            select(OutboxEventModel.event_id)
            .where(
                or_(
                    and_(
                        OutboxEventModel.status == OutboxEventStatus.PUBLISHED,
                        OutboxEventModel.processed_at < cutoff,
                    ),
                    and_(
                        OutboxEventModel.status == OutboxEventStatus.FAILED,
                        OutboxEventModel.created_at < cutoff,
                    ),
                )
            )
            .limit(batch_size)
        )

        result = await db_session.execute(
            delete(OutboxEventModel).where(OutboxEventModel.event_id.in_(subq))
        )
        return getattr(result, "rowcount", None) or 0

    async def reset_stale_processing_events(
        self,
        stale_after_minutes: int = 15,
        session: object | None = None,
    ) -> int:
        """Reset stale PROCESSING events back to PENDING."""
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=stale_after_minutes
        )
        db_session = _get_async_session(session)
        result = await db_session.execute(
            update(OutboxEventModel)
            .where(
                OutboxEventModel.status == OutboxEventStatus.PROCESSING,
                OutboxEventModel.claimed_at < cutoff,
            )
            .values(status=OutboxEventStatus.PENDING)
        )
        return getattr(result, "rowcount", None) or 0


def _to_outbox_event_entity(model: OutboxEventModel) -> OutboxEvent:
    """Map outbox event ORM model to entity."""

    return OutboxEvent(
        event_id=model.event_id,
        event_type=model.event_type,
        aggregate_id=model.aggregate_id,
        aggregate_type=model.aggregate_type,
        payload=model.payload,
        status=model.status,
        created_at=model.created_at,
        processed_at=model.processed_at,
        retry_count=model.retry_count,
        last_error=model.last_error,
    )


def _to_outbox_event_model(event: OutboxEvent) -> OutboxEventModel:
    """Map domain outbox event to ORM model."""

    return OutboxEventModel(
        event_id=event.event_id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        aggregate_type=event.aggregate_type,
        payload=event.payload,
        status=event.status,
        created_at=event.created_at,
        processed_at=event.processed_at,
        retry_count=event.retry_count,
        last_error=event.last_error,
    )


@dataclass(slots=True)
class SqlAlchemyComplaintRepository(ComplaintRepository):
    """SQLAlchemy-backed complaint repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, complaint: Complaint, session: object | None = None
    ) -> None:
        """Persist complaint."""

        db_session = _get_async_session(session)
        model = _to_complaint_model(complaint)
        await db_session.merge(model)

    async def get_by_id(
        self, complaint_id: UUID, session: object | None = None
    ) -> Optional[Complaint]:
        """Get complaint by ID."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(ComplaintModel).where(
                ComplaintModel.complaint_id == complaint_id
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_complaint_entity(result) if result else None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints for a specific order."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(ComplaintModel).where(ComplaintModel.order_id == order_id)
        )
        results = exec_result.scalars()
        return [_to_complaint_entity(item) for item in results]

    async def list_by_reporter(
        self, reporter_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(ComplaintModel).where(
                ComplaintModel.reporter_id == reporter_id
            )
        )
        results = exec_result.scalars()
        return [_to_complaint_entity(item) for item in results]

    async def exists(
        self, order_id: UUID, reporter_id: UUID, session: object | None = None
    ) -> bool:
        """Check if reporter already filed a complaint for this order."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count(ComplaintModel.complaint_id)).where(
                ComplaintModel.order_id == order_id,
                ComplaintModel.reporter_id == reporter_id,
            )
        )
        count = exec_result.scalar()
        return (count or 0) > 0

    async def list_by_status(
        self, status: ComplaintStatus, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints by status."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(ComplaintModel).where(ComplaintModel.status == status)
        )
        results = exec_result.scalars()
        return [_to_complaint_entity(item) for item in results]


def _to_complaint_entity(model: ComplaintModel) -> Complaint:
    """Map complaint ORM model to domain entity."""

    return Complaint(
        complaint_id=model.complaint_id,
        reporter_id=model.reporter_id,
        reported_id=model.reported_id,
        order_id=model.order_id,
        reason=model.reason,
        status=model.status,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", model.created_at),
        reviewed_at=model.reviewed_at,
        file_ids=getattr(model, "file_ids", None),
    )


def _to_complaint_model(complaint: Complaint) -> ComplaintModel:
    """Map complaint domain entity to ORM model."""

    return ComplaintModel(
        complaint_id=complaint.complaint_id,
        reporter_id=complaint.reporter_id,
        reported_id=complaint.reported_id,
        order_id=complaint.order_id,
        reason=complaint.reason,
        status=complaint.status,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at or complaint.created_at,
        reviewed_at=complaint.reviewed_at,
        file_ids=complaint.file_ids,
    )


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

        db_session = _get_async_session(session)
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserReferralBindingModel).where(
                UserReferralBindingModel.referred_user_id == referred_user_id
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserReferralBindingModel)
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(UserReferralBindingModel)
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id
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

        db_session = _get_async_session(session)
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

        db_session = _get_async_session(session)
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

        db_session = _get_async_session(session)
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(UserReferralPendingModel)
            .where(
                UserReferralPendingModel.referrer_user_id == referrer_user_id
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(UserReferralPendingModel)
            .where(
                UserReferralPendingModel.referrer_user_id == referrer_user_id
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

        db_session = _get_async_session(session)
        model = _to_payout_request_model(request)
        db_session.add(model)

    async def get_by_id(
        self, request_id: UUID, session: object | None = None
    ) -> Optional[PayoutRequest]:
        """Fetch payout request by ID."""

        db_session = _get_async_session(session)
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
        db_session = _get_async_session(session)
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

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(PayoutRequestModel).where(
                PayoutRequestModel.user_id == user_id
            )
        )
        return [
            _to_payout_request_entity(m) for m in exec_result.scalars().all()
        ]

    async def list_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Iterable[PayoutRequest]:
        """List payout requests for given user IDs in one query."""
        if not user_ids:
            return []
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(PayoutRequestModel).where(
                PayoutRequestModel.user_id.in_(user_ids)
            )
        )
        return [
            _to_payout_request_entity(m) for m in exec_result.scalars().all()
        ]


@dataclass(slots=True)
class SqlReferralOrderIncomeLoader:
    """Loads referral order income rows in one query to avoid N+1."""

    async def load_referral_order_income_rows(
        self,
        referrer_user_id: UUID,
        limit: int,
        session: object | None = None,
    ) -> list[ReferralOrderIncomeRow]:
        """Return completed-order rows for referred creators (CLOSED, OK)."""
        db_session = _get_async_session(session)
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                InteractionModel,
                and_(
                    InteractionModel.order_id == OrderModel.order_id,
                    InteractionModel.blogger_id
                    == UserReferralBindingModel.referred_user_id,
                    InteractionModel.advertiser_id == OrderModel.advertiser_id,
                ),
            )
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
            )
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id,
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
        db_session = _get_async_session(session)
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
            )
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id,
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
        db_session = _get_async_session(session)
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                InteractionModel,
                and_(
                    InteractionModel.order_id == OrderModel.order_id,
                    InteractionModel.blogger_id
                    == UserReferralBindingModel.referred_user_id,
                    InteractionModel.advertiser_id == OrderModel.advertiser_id,
                ),
            )
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
            )
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id,
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
            )
            .where(
                UserReferralBindingModel.referrer_user_id == referrer_user_id,
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
        db_session = _get_async_session(session)
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                InteractionModel,
                and_(
                    InteractionModel.order_id == OrderModel.order_id,
                    InteractionModel.blogger_id
                    == UserReferralBindingModel.referred_user_id,
                    InteractionModel.advertiser_id == OrderModel.advertiser_id,
                ),
            )
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
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
            .join(PaymentModel, OrderModel.order_id == PaymentModel.order_id)
            .join(
                UserModel,
                UserReferralBindingModel.referred_user_id == UserModel.user_id,
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
        updated_at=getattr(model, "updated_at", model.requested_at),
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
    )


@dataclass(slots=True)
class SqlAlchemyCountryRepository(CountryRepository):
    """SQLAlchemy-backed country repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Country]:
        """List enabled countries."""
        if session is not None:
            db_session = _get_async_session(session)
            exec_result = await db_session.execute(
                select(CountryModel).where(CountryModel.enabled.is_(True))
            )
            rows = exec_result.scalars().all()
            return [_to_country_entity(row) for row in rows]
        async with self.session_factory() as db_session:
            exec_result = await db_session.execute(
                select(CountryModel).where(CountryModel.enabled.is_(True))
            )
            rows = exec_result.scalars().all()
            return [_to_country_entity(row) for row in rows]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Country]:
        """Fetch country by code."""
        if session is not None:
            db_session = _get_async_session(session)
            exec_result = await db_session.execute(
                select(CountryModel).where(CountryModel.code == code)
            )
            result = exec_result.scalar_one_or_none()
            return _to_country_entity(result) if result else None
        async with self.session_factory() as db_session:
            exec_result = await db_session.execute(
                select(CountryModel).where(CountryModel.code == code)
            )
            result = exec_result.scalar_one_or_none()
            return _to_country_entity(result) if result else None


def _to_country_entity(model: CountryModel) -> Country:
    """Map country ORM model to domain entity."""
    return Country(
        code=model.code,
        name_native=model.name_native,
        currency_code=model.currency_code,
        currency_symbol=model.currency_symbol,
        enabled=model.enabled,
    )
