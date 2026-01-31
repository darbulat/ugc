"""SQLAlchemy ORM models for persistence."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.domain.enums import (
    AudienceGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OutboxEventStatus,
    PaymentStatus,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.base import Base


_ENUM_NAME_MAP: dict[type[StrEnum], str] = {
    MessengerType: "messenger_type",
    UserStatus: "user_status",
    AudienceGender: "audience_gender",
    OrderStatus: "order_status",
    InteractionStatus: "interaction_status",
    ComplaintStatus: "complaint_status",
    OutboxEventStatus: "outbox_event_status",
    PaymentStatus: "payment_status",
    WorkFormat: "work_format",
}


def _enum_column(enum_class: type[StrEnum]) -> Enum:
    """Create a SQLAlchemy Enum using enum values."""

    return Enum(
        enum_class,
        name=_ENUM_NAME_MAP[enum_class],
        values_callable=lambda enums: [e.value for e in enums],
        validate_strings=True,
        native_enum=True,
    )


class UserModel(Base):
    """User ORM model."""

    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    messenger_type: Mapped[MessengerType] = mapped_column(
        _enum_column(MessengerType),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[UserStatus] = mapped_column(_enum_column(UserStatus), nullable=False)
    issue_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    role_chosen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_role_reminder_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BloggerProfileModel(Base):
    """Blogger profile ORM model."""

    __tablename__ = "blogger_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    instagram_url: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    city: Mapped[str] = mapped_column(String, nullable=False, server_default=text("''"))
    topics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    audience_gender: Mapped[AudienceGender] = mapped_column(
        _enum_column(AudienceGender), nullable=False
    )
    audience_age_min: Mapped[int] = mapped_column(Integer, nullable=False)
    audience_age_max: Mapped[int] = mapped_column(Integer, nullable=False)
    audience_geo: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    barter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    work_format: Mapped[WorkFormat] = mapped_column(
        _enum_column(WorkFormat), nullable=False, server_default=text("'ugc_only'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AdvertiserProfileModel(Base):
    """Advertiser profile ORM model."""

    __tablename__ = "advertiser_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contact: Mapped[str] = mapped_column(String, nullable=False)  # phone for contact
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class OrderModel(Base):
    """Order ORM model."""

    __tablename__ = "orders"

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    advertiser_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    product_link: Mapped[str] = mapped_column(String, nullable=False)
    offer_text: Mapped[str] = mapped_column(Text, nullable=False)
    ugc_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    barter_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    bloggers_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _enum_column(OrderStatus), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    contacts_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ContactPricingModel(Base):
    """Contact pricing ORM model."""

    __tablename__ = "contact_pricing"

    bloggers_count: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OrderResponseModel(Base):
    """Order response ORM model."""

    __tablename__ = "order_responses"

    response_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
    )
    blogger_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InteractionModel(Base):
    """Interaction ORM model."""

    __tablename__ = "interactions"

    interaction_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
    )
    blogger_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    advertiser_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[InteractionStatus] = mapped_column(
        _enum_column(InteractionStatus), nullable=False
    )
    from_advertiser: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    from_blogger: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    postpone_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    next_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class InstagramVerificationCodeModel(Base):
    """Instagram verification code ORM model."""

    __tablename__ = "instagram_verification_codes"

    code_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ComplaintModel(Base):
    """Complaint ORM model."""

    __tablename__ = "complaints"

    complaint_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    reporter_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ComplaintStatus] = mapped_column(
        _enum_column(ComplaintStatus), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PaymentModel(Base):
    """Payment ORM model."""

    __tablename__ = "payments"

    payment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        _enum_column(PaymentStatus), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FsmDraftModel(Base):
    """FSM draft ORM model for saving partial form data when user clicks Support."""

    __tablename__ = "fsm_drafts"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    flow_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_key: Mapped[str] = mapped_column(String(128), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OutboxEventModel(Base):
    """Outbox event ORM model for reliable event publishing."""

    __tablename__ = "outbox_events"

    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxEventStatus] = mapped_column(
        _enum_column(OutboxEventStatus),
        nullable=False,
        default=OutboxEventStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
