"""Domain entities for the UGC bot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from ugc_bot.domain.enums import OutboxEventStatus

from ugc_bot.domain.enums import (
    AudienceGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)


@dataclass(frozen=True)
class User:
    """Core user entity."""

    user_id: UUID
    external_id: str
    messenger_type: MessengerType
    username: str
    status: UserStatus
    issue_count: int
    created_at: datetime
    role_chosen_at: Optional[datetime] = None
    last_role_reminder_at: Optional[datetime] = None


@dataclass(frozen=True)
class BloggerProfile:
    """Blogger profile entity."""

    user_id: UUID
    instagram_url: str
    confirmed: bool
    topics: dict
    audience_gender: AudienceGender
    audience_age_min: int
    audience_age_max: int
    audience_geo: str
    price: float
    updated_at: datetime


@dataclass(frozen=True)
class AdvertiserProfile:
    """Advertiser profile entity."""

    user_id: UUID
    contact: str


@dataclass(frozen=True)
class Order:
    """Order entity posted by an advertiser."""

    order_id: UUID
    advertiser_id: UUID
    product_link: str
    offer_text: str
    ugc_requirements: Optional[str]
    barter_description: Optional[str]
    price: float
    bloggers_needed: int
    status: OrderStatus
    created_at: datetime
    contacts_sent_at: Optional[datetime]


@dataclass(frozen=True)
class OrderResponse:
    """Order response entity linking bloggers to orders."""

    response_id: UUID
    order_id: UUID
    blogger_id: UUID
    responded_at: datetime


@dataclass(frozen=True)
class Interaction:
    """Feedback interaction entity after contacts are shared."""

    interaction_id: UUID
    order_id: UUID
    blogger_id: UUID
    advertiser_id: UUID
    status: InteractionStatus
    from_advertiser: Optional[str]
    from_blogger: Optional[str]
    postpone_count: int
    next_check_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class InstagramVerificationCode:
    """Instagram verification code entity."""

    code_id: UUID
    user_id: UUID
    code: str
    expires_at: datetime
    used: bool
    created_at: datetime


@dataclass(frozen=True)
class Complaint:
    """Complaint entity for reporting issues."""

    complaint_id: UUID
    reporter_id: UUID
    reported_id: UUID
    order_id: UUID
    reason: str
    status: ComplaintStatus
    created_at: datetime
    reviewed_at: Optional[datetime]


@dataclass(frozen=True)
class Payment:
    """Payment entity."""

    payment_id: UUID
    order_id: UUID
    provider: str
    status: PaymentStatus
    amount: float
    currency: str
    external_id: str
    created_at: datetime
    paid_at: Optional[datetime]


@dataclass(frozen=True)
class ContactPricing:
    """Contact pricing entity."""

    bloggers_count: int
    price: float
    updated_at: datetime


@dataclass(frozen=True)
class OutboxEvent:
    """Outbox event entity for reliable event publishing."""

    event_id: UUID
    event_type: str
    aggregate_id: str
    aggregate_type: str
    payload: dict
    status: OutboxEventStatus
    created_at: datetime
    processed_at: Optional[datetime]
    retry_count: int
    last_error: Optional[str]
