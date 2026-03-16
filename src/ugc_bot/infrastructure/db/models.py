"""SQLAlchemy ORM models for persistence."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    PaymentStatus,
    PayoutRequestStatus,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.base import Base


class _GeometryOrText(TypeDecorator):
    """PostgreSQL: Geometry; SQLite: Text (WKT) so tests run without PostGIS."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return Geometry(geometry_type=self.geometry_type, srid=self.srid)
        return Text()

    def __init__(self, geometry_type: str, srid: int = 4326, **kwargs):
        self.geometry_type = geometry_type
        self.srid = srid
        super().__init__(**kwargs)

    def process_bind_param(self, value, dialect):
        """SQLite: WKT string; PostgreSQL: WKT string or WKTElement."""
        if value is None:
            return None
        if dialect.name != "postgresql":
            if hasattr(value, "desc"):
                return value.desc
            return value
        if isinstance(value, str):
            return WKTElement(value, srid=self.srid)
        return value

    def process_result_value(self, value, dialect):
        """Return value as-is (string from SQLite, WKB from PostgreSQL)."""
        return value


_ENUM_NAME_MAP: dict[type[StrEnum], str] = {
    MessengerType: "messenger_type",
    UserStatus: "user_status",
    AudienceGender: "audience_gender",
    BloggerGender: "blogger_gender",
    OrderStatus: "order_status",
    OrderType: "order_type",
    InteractionStatus: "interaction_status",
    ComplaintStatus: "complaint_status",
    OutboxEventStatus: "outbox_event_status",
    PaymentStatus: "payment_status",
    PayoutRequestStatus: "payout_request_status",
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
    status: Mapped[UserStatus] = mapped_column(
        _enum_column(UserStatus), nullable=False
    )
    issue_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    role_chosen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_role_reminder_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    telegram: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    referral_code: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, unique=True
    )
    referral_payout_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, default=None
    )


class BloggerProfileModel(Base):
    """Blogger profile ORM model."""

    __tablename__ = "blogger_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    instagram_url: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    city: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("''")
    )
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
        _enum_column(WorkFormat),
        nullable=False,
        server_default=text("'ugc_only'"),
    )
    wanted_to_change_terms_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    blogger_gender: Mapped[Optional[BloggerGender]] = mapped_column(
        _enum_column(BloggerGender), nullable=True
    )
    instagram_user_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    instagram_followers_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    instagram_username: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    instagram_stats_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    location_geometry: Mapped[Optional[object]] = mapped_column(
        _GeometryOrText(geometry_type="MULTIPOINT", srid=4326),
        nullable=True,
    )
    country: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'russia'")
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'RUB'")
    )
    agreement_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InstagramStatsModel(Base):
    """Instagram stats ORM model (Rapid API response per user)."""

    __tablename__ = "instagram_stats"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    followers_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    follows_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    media_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    instagram_username: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    biography: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'rapid_api'")
    )
    instagram_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )


class AdvertiserProfileModel(Base):
    """Advertiser profile ORM model."""

    __tablename__ = "advertiser_profiles"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contact: Mapped[str] = mapped_column(
        String, nullable=False
    )  # phone for contact
    brand: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    site_link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    company_activity: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    agreement_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
    order_type: Mapped[OrderType] = mapped_column(
        _enum_column(OrderType),
        nullable=False,
        server_default=text("'ugc_only'"),
    )
    product_link: Mapped[str] = mapped_column(String, nullable=False)
    offer_text: Mapped[str] = mapped_column(Text, nullable=False)
    barter_description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    bloggers_needed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        _enum_column(OrderStatus), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    content_usage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    deadlines: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    geography: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    product_photo_file_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    min_followers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_followers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_publications: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    max_publications: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    required_blogger_gender: Mapped[Optional[BloggerGender]] = mapped_column(
        _enum_column(BloggerGender), nullable=True
    )
    filter_by_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    price_filter_delta: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    filter_by_placement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    filter_by_barter: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    location_geometry: Mapped[Optional[object]] = mapped_column(
        _GeometryOrText(geometry_type="MULTIPOLYGON", srid=4326),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'RUB'")
    )
    last_round_robin_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )


class CountryModel(Base):
    """Country ORM model."""

    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_native: Mapped[str] = mapped_column(String, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    currency_symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    locale: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'ru'")
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class LanguageModel(Base):
    """Language ORM model."""

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name_native: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class ContactPricingModel(Base):
    """Contact pricing ORM model."""

    __tablename__ = "contact_pricing"

    bloggers_count: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BotTextModel(Base):
    """Localized bot text ORM model (key, locale -> value)."""

    __tablename__ = "bot_texts"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    locale: Mapped[str] = mapped_column(String(16), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class OfferDispatchModel(Base):
    """ORM model for tracking offer dispatches and responses."""

    __tablename__ = "offer_dispatches"

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    blogger_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted: Mapped[Optional[bool]] = mapped_column(Boolean(), nullable=True)
    in_offer: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default=text("true")
    )
    manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )


class ManagerOrderModel(Base):
    """Manager-to-order assignment ORM model."""

    __tablename__ = "manager_orders"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    file_ids: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    status: Mapped[ComplaintStatus] = mapped_column(
        _enum_column(ComplaintStatus), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
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
        _enum_column(PaymentStatus), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class NpsResponseModel(Base):
    """NPS response ORM model (user rating after feedback)."""

    __tablename__ = "nps_responses"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
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
    aggregate_id: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
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
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class UserReferralBindingModel(Base):
    """Referrer-to-referred user binding ORM model."""

    __tablename__ = "user_referral_bindings"

    referrer_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    referred_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserReferralPendingModel(Base):
    """Pending referral binding until creator registration."""

    __tablename__ = "user_referral_pending"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    referrer_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PayoutRequestModel(Base):
    """Payout request ORM model for users (referrers)."""

    __tablename__ = "payout_requests"

    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[PayoutRequestStatus] = mapped_column(
        _enum_column(PayoutRequestStatus),
        nullable=False,
        server_default=text("'pending'"),
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
