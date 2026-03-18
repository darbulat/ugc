"""Domain entities for the UGC bot."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

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
    ReferralIncomeType,
    UserStatus,
    WorkFormat,
)


@dataclass(frozen=True)
class Language:
    """Language entity for multi-language support."""

    code: str
    name_native: str
    enabled: bool = True


@dataclass(frozen=True)
class Country:
    """Country entity for multi-country support."""

    code: str
    name_native: str
    currency_code: str
    currency_symbol: str
    tax_rate: Decimal = field(default_factory=lambda: Decimal("0"))
    enabled: bool = True


@dataclass(frozen=True)
class User:
    """Core user entity.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "User(" src/
    3. For new users: set value or default in constructor. For updates of
       existing user: use dataclasses.replace(user, ...) so the new field
       is preserved.
    4. Add the field to the regression test optional-fields list in
       test_user_role_service.py if optional.
    5. Update user entity/model mapping in infrastructure/db/repositories.py.
    """

    user_id: UUID
    external_id: str
    messenger_type: MessengerType
    username: str
    status: UserStatus
    issue_count: int
    created_at: datetime
    role_chosen_at: Optional[datetime] = None
    last_role_reminder_at: Optional[datetime] = None
    telegram: Optional[str] = None
    admin: bool = False
    referral_code: Optional[str] = None
    referral_payout_rate: Optional[Decimal] = None
    updated_at: Optional[datetime] = None
    country: Optional[str] = None
    language: Optional[str] = None


@dataclass(frozen=True)
class BloggerProfile:
    """Blogger profile entity.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "BloggerProfile(" src/
    3. For new profiles (registration): set value or default in constructor.
       For updates of existing profile: use dataclasses.replace(profile, ...)
       so the new field is preserved from profile.
    4. Add the field to the regression test optional-fields list in
       test_blogger_registration_service.py
       (_BLOGGER_PROFILE_OPTIONAL_FIELDS and helper for full profile).
    5. Update _to_blogger_profile_entity and _to_blogger_profile_model in
       infrastructure/db/repositories.py.
    """

    user_id: UUID
    instagram_url: str
    confirmed: bool
    city: str
    topics: dict
    audience_gender: AudienceGender
    audience_age_min: int
    audience_age_max: int
    audience_geo: str
    price: float
    barter: bool
    work_format: WorkFormat
    updated_at: datetime
    wanted_to_change_terms_count: int = 0
    created_at: Optional[datetime] = None
    blogger_gender: Optional[BloggerGender] = None
    instagram_user_id: Optional[str] = None
    instagram_followers_count: Optional[int] = None
    instagram_username: Optional[str] = None
    instagram_stats_fetched_at: Optional[datetime] = None
    birth_date: Optional[date] = None
    region: Optional[str] = None
    # WKT MultiPoint (SRID 4326), e.g. "MULTIPOINT((37.6 55.75))" (lon lat)
    location_geometry: Optional[str] = None
    country: str = ""
    currency: str = "RUB"
    agreement_confirmed_at: Optional[datetime] = None


@dataclass(frozen=True)
class InstagramStats:
    """Instagram account statistics (per user), with data source provider."""

    user_id: UUID
    raw_response: dict
    fetched_at: datetime
    followers_count: Optional[int] = None
    follows_count: Optional[int] = None
    media_count: Optional[int] = None
    instagram_username: Optional[str] = None
    biography: Optional[str] = None
    provider: str = "rapid_api"
    instagram_id: Optional[str] = None


@dataclass(frozen=True)
class AdvertiserProfile:
    """Advertiser profile entity.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "AdvertiserProfile(" src/
    3. For new profiles: set value or default. For updates of existing
       profile: use dataclasses.replace(profile, ...) so the new field
       is preserved.
    4. Add the field to the regression test optional-fields list in
       test_advertiser_registration_service.py if optional.
    5. Update _to_advertiser_profile_entity and _to_advertiser_profile_model
       in infrastructure/db/repositories.py.
    """

    user_id: UUID
    phone: str
    brand: str
    site_link: Optional[str] = None
    city: Optional[str] = None
    company_activity: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    agreement_confirmed_at: Optional[datetime] = None


@dataclass(frozen=True)
class Order:
    """Order entity posted by an advertiser.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "Order(" src/
    3. For new orders: set value or default. For updates (status change etc.):
       use dataclasses.replace(order, ...) so the new field is preserved.
    4. Update order entity/model mapping in infrastructure/db/repositories.py.
    """

    order_id: UUID
    advertiser_id: UUID
    order_type: OrderType
    product_link: str
    offer_text: str
    barter_description: Optional[str]
    price: float
    bloggers_needed: int
    status: OrderStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    content_usage: Optional[str] = None
    deadlines: Optional[str] = None
    # Advertiser's answer: where creator may be (1–10 cities, regions, or "РФ").
    # Used for barter orders and product delivery.
    geography: Optional[str] = None
    product_photo_file_id: Optional[str] = None
    min_followers: Optional[int] = None
    max_followers: Optional[int] = None
    # Admin-only filters for matching bloggers (optional)
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    min_publications: Optional[int] = None
    max_publications: Optional[int] = None
    required_blogger_gender: Optional[BloggerGender] = None
    # Admin-only: filter creators by price / placement / barter when dispatching
    filter_by_price: bool = False
    # filter_by_price: range [price - delta, price + delta]; delta in admin
    price_filter_delta: Optional[float] = None
    filter_by_placement: bool = False
    filter_by_barter: bool = False
    # WKT MULTIPOLYGON (SRID 4326) for countries/regions/cities from geography.
    location_geometry: Optional[str] = None
    currency: str = "RUB"
    last_round_robin_index: int = 0


@dataclass(frozen=True)
class OfferDispatch:
    """Offer dispatch: sent offer and optional response (accepted/skip).

    When adding a new field: find usages with grep -r "OfferDispatch(" src/;
    for updates use dataclasses.replace(dispatch, ...). Update repo mapping.
    """

    order_id: UUID
    blogger_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    accepted: Optional[bool] = (
        None  # True=Готов снять, False=Пропустить/overflow, None=no response
    )
    in_offer: bool = (
        True  # Counted toward order; at most bloggers_needed per order
    )
    manager_id: Optional[UUID] = None
    ugc_video_url: Optional[str] = None


@dataclass(frozen=True)
class ManagerOrder:
    """Manager-to-order assignment for round-robin response routing."""

    user_id: UUID
    order_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None


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
    """Complaint entity for reporting issues.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "Complaint(" src/
    3. For new complaints: set value or default. For updates (dismiss/resolve):
       use dataclasses.replace(complaint, ...) so the new field is preserved.
    4. Add the field to the regression test optional-fields list in
       test_complaint_service.py if optional.
    5. Update complaint entity/model mapping in db/repositories.py.
    """

    complaint_id: UUID
    reporter_id: UUID
    reported_id: UUID
    order_id: UUID
    reason: str
    status: ComplaintStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    file_ids: Optional[list[str]] = None


@dataclass(frozen=True)
class Payment:
    """Payment entity.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "Payment(" src/
    3. For updates of existing payment use dataclasses.replace(payment, ...).
    4. Update payment entity/model mapping in infrastructure/db/repositories.py.
    """

    payment_id: UUID
    order_id: UUID
    provider: str
    status: PaymentStatus
    amount: float
    currency: str
    external_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None


@dataclass(frozen=True)
class ContactPricing:
    """Contact pricing entity.

    When adding a new field: find usages with grep -r "ContactPricing(" src/;
    for updates use dataclasses.replace(pricing, ...). Update repo mapping.
    """

    country_code: str
    bloggers_count: int
    price: Decimal
    currency: str
    updated_at: datetime
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class OutboxEvent:
    """Outbox event entity for reliable event publishing.

    When adding a new field: find usages with grep -r "OutboxEvent(" src/;
    for updates use dataclasses.replace(event, ...). Update repo mapping.
    """

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


@dataclass(frozen=True)
class UserReferralBinding:
    """Referrer-to-referred user binding (permanent)."""

    referrer_user_id: UUID
    referred_user_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class UserReferralPending:
    """Pending referral binding until creator registration."""

    user_id: UUID
    referrer_user_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class PayoutRequest:
    """Payout request by user (referrer).

    When adding a new field: find usages with grep -r "PayoutRequest(" src/;
    for updates use dataclasses.replace(request, ...). Update repo mapping.
    """

    request_id: UUID
    user_id: UUID
    requested_at: datetime
    status: PayoutRequestStatus
    amount: Optional[Decimal] = None
    updated_at: Optional[datetime] = None
    currency: str = "RUB"


@dataclass(frozen=True)
class ReferralIncomeEntry:
    """One referral income record for a completed order."""

    entry_id: UUID
    referrer_user_id: UUID
    referred_user_id: UUID
    order_id: UUID
    income_type: ReferralIncomeType
    currency: str
    platform_revenue: Decimal
    commission_rate: Decimal
    commission_amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class ReferralOrderIncomeRow:
    """One row for referral income (one completed order)."""

    creator_created_at: datetime
    order_completed_at: datetime
    payment_amount: float
    bloggers_needed: int
    order_id: UUID
