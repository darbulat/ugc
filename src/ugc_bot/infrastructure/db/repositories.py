"""SQLAlchemy repository implementations."""

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from datetime import datetime, timezone

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    ComplaintRepository,
    ContactPricingRepository,
    InstagramVerificationRepository,
    InteractionRepository,
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
    OutboxEventStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    OrderModel,
    OrderResponseModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)


@dataclass(slots=True)
class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed user repository."""

    session_factory: sessionmaker[Session]

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Fetch a user by ID."""

        with self.session_factory() as session:
            result = session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            ).scalar_one_or_none()
            return _to_user_entity(result) if result else None

    def get_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        with self.session_factory() as session:
            result = session.execute(
                select(UserModel).where(
                    UserModel.external_id == external_id,
                    UserModel.messenger_type == messenger_type.value,
                )
            ).scalar_one_or_none()
            return _to_user_entity(result) if result else None

    def save(self, user: User) -> None:
        """Persist a user."""

        with self.session_factory() as session:
            model = _to_user_model(user)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyBloggerProfileRepository(BloggerProfileRepository):
    """SQLAlchemy-backed blogger profile repository."""

    session_factory: sessionmaker[Session]

    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        with self.session_factory() as session:
            result = session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.user_id == user_id
                )
            ).scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    def get_by_instagram_url(self, instagram_url: str) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

        with self.session_factory() as session:
            result = session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.instagram_url == instagram_url
                )
            ).scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile."""

        with self.session_factory() as session:
            model = _to_blogger_profile_model(profile)
            session.merge(model)
            session.commit()

    def list_confirmed_user_ids(self) -> list[UUID]:
        """List confirmed blogger user ids."""

        with self.session_factory() as session:
            # Get users who have blogger profiles and are confirmed
            results = session.execute(
                select(UserModel.user_id)
                .join(
                    BloggerProfileModel,
                    UserModel.user_id == BloggerProfileModel.user_id,
                )
                .where(UserModel.confirmed.is_(True))
            ).scalars()
            return list(results)


@dataclass(slots=True)
class SqlAlchemyAdvertiserProfileRepository(AdvertiserProfileRepository):
    """SQLAlchemy-backed advertiser profile repository."""

    session_factory: sessionmaker[Session]

    def get_by_user_id(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        with self.session_factory() as session:
            result = session.execute(
                select(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == user_id
                )
            ).scalar_one_or_none()
            return _to_advertiser_profile_entity(result) if result else None

    def save(self, profile: AdvertiserProfile) -> None:
        """Persist advertiser profile."""

        with self.session_factory() as session:
            model = _to_advertiser_profile_model(profile)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyInstagramVerificationRepository(InstagramVerificationRepository):
    """SQLAlchemy-backed Instagram verification repository."""

    session_factory: sessionmaker[Session]

    def save(self, code: InstagramVerificationCode) -> None:
        """Persist verification code."""

        with self.session_factory() as session:
            model = _to_verification_model(code)
            session.merge(model)
            session.commit()

    def get_valid_code(
        self, user_id: UUID, code: str
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            result = session.execute(
                select(InstagramVerificationCodeModel).where(
                    InstagramVerificationCodeModel.user_id == user_id,
                    InstagramVerificationCodeModel.code == code,
                    InstagramVerificationCodeModel.used.is_(False),
                    InstagramVerificationCodeModel.expires_at > now,
                )
            ).scalar_one_or_none()
            if result is None:
                return None
            if result.used or result.expires_at <= now:
                return None
            if result.code != code or result.user_id != user_id:
                return None
            return _to_verification_entity(result)

    def mark_used(self, code_id: UUID) -> None:
        """Mark verification code as used."""

        with self.session_factory() as session:
            model = session.get(InstagramVerificationCodeModel, code_id)
            if model is None:
                return
            model.used = True
            session.commit()

    def get_valid_code_by_code(self, code: str) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code by code string."""

        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            result = session.execute(
                select(InstagramVerificationCodeModel).where(
                    InstagramVerificationCodeModel.code == code,
                    InstagramVerificationCodeModel.used.is_(False),
                    InstagramVerificationCodeModel.expires_at > now,
                )
            ).scalar_one_or_none()
            if result is None:
                return None
            if result.used or result.expires_at <= now:
                return None
            return _to_verification_entity(result)


@dataclass(slots=True)
class SqlAlchemyOrderRepository(OrderRepository):
    """SQLAlchemy-backed order repository."""

    session_factory: sessionmaker[Session]

    def get_by_id(self, order_id: UUID) -> Optional[Order]:
        """Fetch order by ID."""

        with self.session_factory() as session:
            result = session.execute(
                select(OrderModel).where(OrderModel.order_id == order_id)
            ).scalar_one_or_none()
            return _to_order_entity(result) if result else None

    def list_active(self) -> Iterable[Order]:
        """List active orders."""

        with self.session_factory() as session:
            result = session.execute(
                select(OrderModel).where(OrderModel.status == OrderStatus.ACTIVE)
            ).scalars()
            return [_to_order_entity(item) for item in result]

    def list_by_advertiser(self, advertiser_id: UUID) -> Iterable[Order]:
        """List orders by advertiser."""

        with self.session_factory() as session:
            result = session.execute(
                select(OrderModel).where(OrderModel.advertiser_id == advertiser_id)
            ).scalars()
            return [_to_order_entity(item) for item in result]

    def list_with_contacts_before(self, cutoff: datetime) -> Iterable[Order]:
        """List orders with contacts_sent_at before cutoff."""

        with self.session_factory() as session:
            result = session.execute(
                select(OrderModel).where(
                    OrderModel.contacts_sent_at.is_not(None),
                    OrderModel.contacts_sent_at <= cutoff,
                )
            ).scalars()
            return [_to_order_entity(item) for item in result]

    def count_by_advertiser(self, advertiser_id: UUID) -> int:
        """Count orders by advertiser."""

        with self.session_factory() as session:
            result = session.execute(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.advertiser_id == advertiser_id)
            ).scalar_one()
            return int(result)

    def save(self, order: Order) -> None:
        """Persist order."""

        with self.session_factory() as session:
            model = _to_order_model(order)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyPaymentRepository(PaymentRepository):
    """SQLAlchemy-backed payment repository."""

    session_factory: sessionmaker[Session]

    def get_by_order(self, order_id: UUID) -> Optional[Payment]:
        """Fetch payment by order id."""

        with self.session_factory() as session:
            result = session.execute(
                select(PaymentModel).where(PaymentModel.order_id == order_id)
            ).scalar_one_or_none()
            return _to_payment_entity(result) if result else None

    def get_by_external_id(self, external_id: str) -> Optional[Payment]:
        """Fetch payment by provider external id."""

        with self.session_factory() as session:
            result = session.execute(
                select(PaymentModel).where(PaymentModel.external_id == external_id)
            ).scalar_one_or_none()
            return _to_payment_entity(result) if result else None

    def save(self, payment: Payment) -> None:
        """Persist payment."""

        with self.session_factory() as session:
            model = _to_payment_model(payment)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyContactPricingRepository(ContactPricingRepository):
    """SQLAlchemy-backed contact pricing repository."""

    session_factory: sessionmaker[Session]

    def get_by_bloggers_count(self, bloggers_count: int) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""

        with self.session_factory() as session:
            result = session.execute(
                select(ContactPricingModel).where(
                    ContactPricingModel.bloggers_count == bloggers_count
                )
            ).scalar_one_or_none()
            return _to_contact_pricing_entity(result) if result else None


@dataclass(slots=True)
class SqlAlchemyOrderResponseRepository(OrderResponseRepository):
    """SQLAlchemy-backed order response repository."""

    session_factory: sessionmaker[Session]

    def save(self, response: OrderResponse) -> None:
        """Persist order response."""

        with self.session_factory() as session:
            model = _to_order_response_model(response)
            session.merge(model)
            session.commit()

    def list_by_order(self, order_id: UUID) -> list[OrderResponse]:
        """List responses by order."""

        with self.session_factory() as session:
            results = session.execute(
                select(OrderResponseModel).where(
                    OrderResponseModel.order_id == order_id
                )
            ).scalars()
            return [_to_order_response_entity(item) for item in results]

    def exists(self, order_id: UUID, blogger_id: UUID) -> bool:
        """Check if blogger already responded."""

        with self.session_factory() as session:
            result = session.execute(
                select(func.count())
                .select_from(OrderResponseModel)
                .where(
                    OrderResponseModel.order_id == order_id,
                    OrderResponseModel.blogger_id == blogger_id,
                )
            ).scalar_one()
            return int(result) > 0

    def count_by_order(self, order_id: UUID) -> int:
        """Count responses by order."""

        with self.session_factory() as session:
            result = session.execute(
                select(func.count())
                .select_from(OrderResponseModel)
                .where(OrderResponseModel.order_id == order_id)
            ).scalar_one()
            return int(result)


@dataclass(slots=True)
class SqlAlchemyInteractionRepository(InteractionRepository):
    """SQLAlchemy-backed interaction repository."""

    session_factory: sessionmaker[Session]

    def get_by_id(self, interaction_id: UUID) -> Optional[Interaction]:
        """Fetch interaction by id."""

        with self.session_factory() as session:
            result = session.execute(
                select(InteractionModel).where(
                    InteractionModel.interaction_id == interaction_id
                )
            ).scalar_one_or_none()
            return _to_interaction_entity(result) if result else None

    def get_by_participants(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

        with self.session_factory() as session:
            result = session.execute(
                select(InteractionModel).where(
                    InteractionModel.order_id == order_id,
                    InteractionModel.blogger_id == blogger_id,
                    InteractionModel.advertiser_id == advertiser_id,
                )
            ).scalar_one_or_none()
            return _to_interaction_entity(result) if result else None

    def list_by_order(self, order_id: UUID) -> Iterable[Interaction]:
        """List interactions for order."""

        with self.session_factory() as session:
            results = session.execute(
                select(InteractionModel).where(InteractionModel.order_id == order_id)
            ).scalars()
            return [_to_interaction_entity(item) for item in results]

    def list_due_for_feedback(self, cutoff: datetime) -> Iterable[Interaction]:
        """List interactions due for feedback."""

        with self.session_factory() as session:
            results = session.execute(
                select(InteractionModel).where(
                    InteractionModel.next_check_at <= cutoff,
                    InteractionModel.status == InteractionStatus.PENDING,
                )
            ).scalars()
            return [_to_interaction_entity(item) for item in results]

    def list_by_status(self, status: InteractionStatus) -> Iterable[Interaction]:
        """List interactions by status."""

        with self.session_factory() as session:
            results = session.execute(
                select(InteractionModel).where(InteractionModel.status == status)
            ).scalars()
            return [_to_interaction_entity(item) for item in results]

    def save(self, interaction: Interaction) -> None:
        """Persist interaction."""

        with self.session_factory() as session:
            model = _to_interaction_model(interaction)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class NoopOfferBroadcaster(OfferBroadcaster):
    """No-op broadcaster for MVP."""

    def broadcast_order(self, order: Order) -> None:
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
        instagram_url=model.instagram_url,
        confirmed=model.confirmed,
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
        instagram_url=user.instagram_url,
        confirmed=user.confirmed,
    )


def _to_blogger_profile_entity(
    model: BloggerProfileModel,
) -> BloggerProfile:
    """Map blogger profile ORM model to domain entity."""

    return BloggerProfile(
        user_id=model.user_id,
        instagram_url=model.instagram_url,
        topics=model.topics,
        audience_gender=model.audience_gender,
        audience_age_min=model.audience_age_min,
        audience_age_max=model.audience_age_max,
        audience_geo=model.audience_geo,
        price=float(model.price),
        updated_at=model.updated_at,
    )


def _to_blogger_profile_model(
    profile: BloggerProfile,
) -> BloggerProfileModel:
    """Map domain blogger profile entity to ORM model."""

    return BloggerProfileModel(
        user_id=profile.user_id,
        instagram_url=profile.instagram_url,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
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

    return AdvertiserProfile(user_id=model.user_id, contact=model.contact)


def _to_advertiser_profile_model(
    profile: AdvertiserProfile,
) -> AdvertiserProfileModel:
    """Map domain advertiser profile entity to ORM model."""

    return AdvertiserProfileModel(
        user_id=profile.user_id,
        contact=profile.contact,
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
        product_link=model.product_link,
        offer_text=model.offer_text,
        ugc_requirements=model.ugc_requirements,
        barter_description=model.barter_description,
        price=float(model.price),
        bloggers_needed=model.bloggers_needed,
        status=model.status,
        created_at=model.created_at,
        contacts_sent_at=model.contacts_sent_at,
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
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=order.status,
        created_at=order.created_at,
        contacts_sent_at=order.contacts_sent_at,
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

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def save(self, event: OutboxEvent) -> None:
        """Persist outbox event."""

        model = _to_outbox_event_model(event)
        with self.session_factory() as session:
            session.add(model)
            session.commit()

    def get_pending_events(self, limit: int = 100) -> List[OutboxEvent]:
        """Get pending events for processing."""

        with self.session_factory() as session:
            models = (
                session.query(OutboxEventModel)
                .filter(OutboxEventModel.status == OutboxEventStatus.PENDING)
                .order_by(OutboxEventModel.created_at)
                .limit(limit)
                .all()
            )
            return [_to_outbox_event_entity(model) for model in models]

    def mark_as_processing(self, event_id: UUID) -> None:
        """Mark event as processing."""

        with self.session_factory() as session:
            session.query(OutboxEventModel).filter(
                OutboxEventModel.event_id == event_id
            ).update({"status": OutboxEventStatus.PROCESSING})
            session.commit()

    def mark_as_published(self, event_id: UUID, processed_at: datetime) -> None:
        """Mark event as published."""

        with self.session_factory() as session:
            session.query(OutboxEventModel).filter(
                OutboxEventModel.event_id == event_id
            ).update(
                {"status": OutboxEventStatus.PUBLISHED, "processed_at": processed_at}
            )
            session.commit()

    def mark_as_failed(self, event_id: UUID, error: str, retry_count: int) -> None:
        """Mark event as failed with retry."""

        with self.session_factory() as session:
            session.query(OutboxEventModel).filter(
                OutboxEventModel.event_id == event_id
            ).update(
                {
                    "status": OutboxEventStatus.FAILED,
                    "last_error": error,
                    "retry_count": retry_count,
                }
            )
            session.commit()

    def get_by_id(self, event_id: UUID) -> Optional[OutboxEvent]:
        """Get event by ID."""

        with self.session_factory() as session:
            model = (
                session.query(OutboxEventModel)
                .filter(OutboxEventModel.event_id == event_id)
                .first()
            )
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

    session_factory: sessionmaker[Session]

    def save(self, complaint: Complaint) -> None:
        """Persist complaint."""

        with self.session_factory() as session:
            model = _to_complaint_model(complaint)
            session.add(model)
            session.commit()

    def get_by_id(self, complaint_id: UUID) -> Optional[Complaint]:
        """Get complaint by ID."""

        with self.session_factory() as session:
            result = session.execute(
                select(ComplaintModel).where(
                    ComplaintModel.complaint_id == complaint_id
                )
            ).scalar_one_or_none()
            return _to_complaint_entity(result) if result else None

    def list_by_order(self, order_id: UUID) -> Iterable[Complaint]:
        """List complaints for a specific order."""

        with self.session_factory() as session:
            results = session.execute(
                select(ComplaintModel).where(ComplaintModel.order_id == order_id)
            ).scalars()
            return [_to_complaint_entity(item) for item in results]

    def list_by_reporter(self, reporter_id: UUID) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

        with self.session_factory() as session:
            results = session.execute(
                select(ComplaintModel).where(ComplaintModel.reporter_id == reporter_id)
            ).scalars()
            return [_to_complaint_entity(item) for item in results]

    def exists(self, order_id: UUID, reporter_id: UUID) -> bool:
        """Check if reporter already filed a complaint for this order."""

        with self.session_factory() as session:
            count = session.execute(
                select(func.count(ComplaintModel.complaint_id)).where(
                    ComplaintModel.order_id == order_id,
                    ComplaintModel.reporter_id == reporter_id,
                )
            ).scalar()
            return (count or 0) > 0

    def list_by_status(self, status: ComplaintStatus) -> Iterable[Complaint]:
        """List complaints by status."""

        with self.session_factory() as session:
            results = session.execute(
                select(ComplaintModel).where(ComplaintModel.status == status)
            ).scalars()
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
    )
