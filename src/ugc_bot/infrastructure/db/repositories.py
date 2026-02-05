"""SQLAlchemy repository implementations."""

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datetime import datetime, timezone

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    ComplaintRepository,
    ContactPricingRepository,
    FsmDraftRepository,
    InstagramVerificationRepository,
    InteractionRepository,
    NpsRepository,
    OfferBroadcaster,
    OrderRepository,
    OrderResponseRepository,
    OutboxRepository,
    PaymentRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    ContactPricing,
    FsmDraft,
    InstagramVerificationCode,
    Interaction,
    Order,
    OrderResponse,
    OutboxEvent,
    Payment,
    User,
)
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    FsmDraftModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    NpsResponseModel,
    OrderModel,
    OrderResponseModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.fsm_draft_serializer import (
    deserialize_fsm_data,
    serialize_fsm_data,
)


def _require_session(session: AsyncSession | None) -> AsyncSession:
    """Ensure an AsyncSession is provided.

    We keep `session: object | None` in repository ports to support in-memory
    repositories in unit tests. SQLAlchemy repositories must always operate
    with an explicit session provided by a higher-level transaction boundary
    (e.g., UnitOfWork / transaction manager).
    """

    if session is None:
        raise RuntimeError(
            "Database session is required. Use a transaction boundary and pass "
            "the session explicitly (e.g., via UnitOfWork)."
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
            query = query.where(UserModel.messenger_type == messenger_type.value)
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
            select(BloggerProfileModel).where(BloggerProfileModel.user_id == user_id)
        )
        result = exec_result.scalar_one_or_none()
        return _to_blogger_profile_entity(result) if result else None

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
        self, session: object | None = None
    ) -> list[UUID]:
        """List confirmed blogger user ids."""

        db_session = _require_session(
            session if isinstance(session, AsyncSession) else None
        )
        exec_result = await db_session.execute(
            select(BloggerProfileModel.user_id).where(
                BloggerProfileModel.confirmed.is_(True)
            )
        )
        results = exec_result.scalars()
        return list(results)


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
class SqlAlchemyInstagramVerificationRepository(InstagramVerificationRepository):
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
            return None
        if result.code != code or result.user_id != user_id:
            return None
        return _to_verification_entity(result)

    async def mark_used(self, code_id: UUID, session: object | None = None) -> None:
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
            select(OrderModel).where(OrderModel.order_id == order_id).with_for_update()
        )
        db_session = _get_async_session(session)
        exec_result = await db_session.execute(stmt)
        result = exec_result.scalar_one_or_none()
        return _to_order_entity(result) if result else None

    async def list_active(self, session: object | None = None) -> Iterable[Order]:
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

    async def save(self, payment: Payment, session: object | None = None) -> None:
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
class SqlAlchemyOrderResponseRepository(OrderResponseRepository):
    """SQLAlchemy-backed order response repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, response: OrderResponse, session: object | None = None
    ) -> None:
        """Persist order response."""

        model = _to_order_response_model(response)
        db_session = _get_async_session(session)
        await db_session.merge(model)

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[OrderResponse]:
        """List responses by order."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderResponseModel).where(OrderResponseModel.order_id == order_id)
        )
        results = exec_result.scalars()
        return [_to_order_response_entity(item) for item in results]

    async def list_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[OrderResponse]:
        """List responses by blogger (orders the blogger responded to)."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OrderResponseModel).where(
                OrderResponseModel.blogger_id == blogger_id
            )
        )
        results = exec_result.scalars()
        return [_to_order_response_entity(item) for item in results]

    async def exists(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OrderResponseModel)
            .where(
                OrderResponseModel.order_id == order_id,
                OrderResponseModel.blogger_id == blogger_id,
            )
        )
        result = exec_result.scalar_one()
        return int(result) > 0

    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count responses by order."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(func.count())
            .select_from(OrderResponseModel)
            .where(OrderResponseModel.order_id == order_id)
        )
        result = exec_result.scalar_one()
        return int(result)


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
            select(InteractionModel).where(InteractionModel.order_id == order_id)
        )
        results = exec_result.scalars()
        return [_to_interaction_entity(item) for item in results]

    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel).where(
                InteractionModel.next_check_at <= cutoff,
                InteractionModel.status == InteractionStatus.PENDING,
            )
        )
        results = exec_result.scalars()
        return [_to_interaction_entity(item) for item in results]

    async def list_by_status(
        self, status: InteractionStatus, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(InteractionModel).where(InteractionModel.status == status)
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


@dataclass(slots=True)
class NoopOfferBroadcaster(OfferBroadcaster):
    """No-op broadcaster for MVP."""

    async def broadcast_order(self, order: Order) -> None:
        """No-op implementation."""

        return None


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
    )


def _to_blogger_profile_entity(
    model: BloggerProfileModel,
) -> BloggerProfile:
    """Map blogger profile ORM model to domain entity."""

    work_format = model.work_format
    if isinstance(work_format, str):
        work_format = WorkFormat(work_format)
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
        wanted_to_change_terms_count=getattr(model, "wanted_to_change_terms_count", 0),
        updated_at=model.updated_at,
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
        updated_at=profile.updated_at,
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


def _to_order_entity(model: OrderModel) -> Order:
    """Map order ORM model to domain entity."""

    return Order(
        order_id=model.order_id,
        advertiser_id=model.advertiser_id,
        order_type=getattr(model, "order_type", None) or OrderType.UGC_ONLY,
        product_link=model.product_link,
        offer_text=model.offer_text,
        ugc_requirements=model.ugc_requirements,
        barter_description=model.barter_description,
        price=float(model.price),
        bloggers_needed=model.bloggers_needed,
        status=model.status,
        created_at=model.created_at,
        completed_at=model.completed_at,
        content_usage=getattr(model, "content_usage", None),
        deadlines=getattr(model, "deadlines", None),
        geography=getattr(model, "geography", None),
    )


def _to_order_response_entity(
    model: OrderResponseModel,
) -> OrderResponse:
    """Map order response ORM model to domain entity."""

    return OrderResponse(
        response_id=model.response_id,
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        responded_at=model.responded_at,
    )


def _to_order_model(order: Order) -> OrderModel:
    """Map domain order entity to ORM model."""

    return OrderModel(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=order.status,
        created_at=order.created_at,
        completed_at=order.completed_at,
        content_usage=order.content_usage,
        deadlines=order.deadlines,
        geography=order.geography,
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
        paid_at=payment.paid_at,
    )


def _to_contact_pricing_entity(model: ContactPricingModel) -> ContactPricing:
    """Map contact pricing ORM model to entity."""

    return ContactPricing(
        bloggers_count=model.bloggers_count,
        price=float(model.price),
        updated_at=model.updated_at,
    )


def _to_order_response_model(
    response: OrderResponse,
) -> OrderResponseModel:
    """Map domain order response entity to ORM model."""

    return OrderResponseModel(
        response_id=response.response_id,
        order_id=response.order_id,
        blogger_id=response.blogger_id,
        responded_at=response.responded_at,
    )


class SqlAlchemyOutboxRepository(OutboxRepository):
    """SQLAlchemy implementation of outbox repository."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def save(self, event: OutboxEvent, session: object | None = None) -> None:
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
        self, event_id: UUID, processed_at: datetime, session: object | None = None
    ) -> None:
        """Mark event as published."""

        db_session = _get_async_session(session)
        await db_session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == event_id)
            .values(status=OutboxEventStatus.PUBLISHED, processed_at=processed_at)
        )

    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed with retry."""

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

    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(OutboxEventModel).where(OutboxEventModel.event_id == event_id)
        )
        model = exec_result.scalar_one_or_none()
        return _to_outbox_event_entity(model) if model else None


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

    async def save(self, complaint: Complaint, session: object | None = None) -> None:
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
            select(ComplaintModel).where(ComplaintModel.complaint_id == complaint_id)
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
            select(ComplaintModel).where(ComplaintModel.reporter_id == reporter_id)
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
        reviewed_at=complaint.reviewed_at,
        file_ids=complaint.file_ids,
    )


@dataclass(slots=True)
class SqlAlchemyFsmDraftRepository(FsmDraftRepository):
    """SQLAlchemy-backed FSM draft repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        user_id: UUID,
        flow_type: str,
        state_key: str,
        data: dict,
        session: object | None = None,
    ) -> None:
        """Save or overwrite draft for user and flow type."""

        db_session = _get_async_session(session)
        serialized = serialize_fsm_data(data)
        model = FsmDraftModel(
            user_id=user_id,
            flow_type=flow_type,
            state_key=state_key,
            data=serialized,
        )
        await db_session.merge(model)

    async def get(
        self,
        user_id: UUID,
        flow_type: str,
        session: object | None = None,
    ) -> Optional[FsmDraft]:
        """Get draft for user and flow type, or None."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(FsmDraftModel).where(
                FsmDraftModel.user_id == user_id,
                FsmDraftModel.flow_type == flow_type,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_fsm_draft_entity(result, flow_type) if result else None

    async def delete(
        self,
        user_id: UUID,
        flow_type: str,
        session: object | None = None,
    ) -> None:
        """Delete draft for user and flow type."""

        db_session = _get_async_session(session)
        exec_result = await db_session.execute(
            select(FsmDraftModel).where(
                FsmDraftModel.user_id == user_id,
                FsmDraftModel.flow_type == flow_type,
            )
        )
        model = exec_result.scalar_one_or_none()
        if model is not None:
            await db_session.delete(model)


def _to_fsm_draft_entity(model: FsmDraftModel, flow_type: str) -> FsmDraft:
    """Map FSM draft ORM model to domain entity with deserialized data."""

    data = deserialize_fsm_data(dict(model.data), flow_type)
    return FsmDraft(
        user_id=model.user_id,
        flow_type=model.flow_type,
        state_key=model.state_key,
        data=data,
        updated_at=model.updated_at,
    )
