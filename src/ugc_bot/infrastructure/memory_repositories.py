"""In-memory repository implementations."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from datetime import datetime, timezone

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    ComplaintRepository,
    ContactPricingRepository,
    InteractionRepository,
    InstagramGraphApiClient,
    InstagramVerificationRepository,
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
    Interaction,
    InstagramVerificationCode,
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


@dataclass
class InMemoryUserRepository(UserRepository):
    """In-memory implementation of user repository."""

    users: Dict[UUID, User] = field(default_factory=dict)
    external_index: Dict[Tuple[str, MessengerType], UUID] = field(default_factory=dict)

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Fetch a user by ID."""

        return self.users.get(user_id)

    def get_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        key = (external_id, messenger_type)
        user_id = self.external_index.get(key)
        return self.users.get(user_id) if user_id else None

    def save(self, user: User) -> None:
        """Persist a user in memory."""

        self.users[user.user_id] = user
        self.external_index[(user.external_id, user.messenger_type)] = user.user_id

    def iter_all(self) -> Iterable[User]:
        """Iterate all users."""

        return list(self.users.values())


@dataclass
class InMemoryBloggerProfileRepository(BloggerProfileRepository):
    """In-memory implementation of blogger profile repository."""

    profiles: Dict[UUID, BloggerProfile] = field(default_factory=dict)

    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        return self.profiles.get(user_id)

    def get_by_instagram_url(self, instagram_url: str) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

        for profile in self.profiles.values():
            if profile.instagram_url == instagram_url:
                return profile
        return None

    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile in memory."""

        self.profiles[profile.user_id] = profile

    def list_confirmed_user_ids(self) -> list[UUID]:
        """List confirmed blogger user ids."""

        return [
            profile.user_id for profile in self.profiles.values() if profile.confirmed
        ]


@dataclass
class InMemoryAdvertiserProfileRepository(AdvertiserProfileRepository):
    """In-memory implementation of advertiser profile repository."""

    profiles: Dict[UUID, AdvertiserProfile] = field(default_factory=dict)

    def get_by_user_id(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        return self.profiles.get(user_id)

    def save(self, profile: AdvertiserProfile) -> None:
        """Persist advertiser profile in memory."""

        self.profiles[profile.user_id] = profile


@dataclass
class InMemoryInstagramVerificationRepository(InstagramVerificationRepository):
    """In-memory implementation of Instagram verification repository."""

    codes: Dict[UUID, InstagramVerificationCode] = field(default_factory=dict)

    def save(self, code: InstagramVerificationCode) -> None:
        """Persist verification code in memory."""

        self.codes[code.code_id] = code

    def get_valid_code(
        self, user_id: UUID, code: str
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

        now = datetime.now(timezone.utc)
        for item in self.codes.values():
            if (
                item.user_id == user_id
                and item.code == code
                and not item.used
                and item.expires_at > now
            ):
                return item
        return None

    def get_valid_code_by_code(self, code: str) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code by code string (for webhook processing)."""

        now = datetime.now(timezone.utc)
        for item in self.codes.values():
            if item.code == code and not item.used and item.expires_at > now:
                return item
        return None

    def mark_used(self, code_id: UUID) -> None:
        """Mark verification code as used."""

        if code_id not in self.codes:
            return
        existing = self.codes[code_id]
        self.codes[code_id] = InstagramVerificationCode(
            code_id=existing.code_id,
            user_id=existing.user_id,
            code=existing.code,
            expires_at=existing.expires_at,
            used=True,
            created_at=existing.created_at,
        )


@dataclass
class InMemoryInstagramGraphApiClient(InstagramGraphApiClient):
    """In-memory implementation of Instagram Graph API client for testing."""

    username_map: Dict[str, str] = field(default_factory=dict)

    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID from in-memory map."""
        return self.username_map.get(instagram_user_id)


@dataclass
class InMemoryOrderRepository(OrderRepository):
    """In-memory implementation of order repository."""

    orders: Dict[UUID, Order] = field(default_factory=dict)

    def get_by_id(self, order_id: UUID) -> Optional[Order]:
        """Fetch order by id."""

        return self.orders.get(order_id)

    def list_active(self) -> Iterable[Order]:
        """List active orders."""

        return [
            order
            for order in self.orders.values()
            if order.status == OrderStatus.ACTIVE
        ]

    def list_by_advertiser(self, advertiser_id: UUID) -> Iterable[Order]:
        """List orders by advertiser."""

        return [
            order
            for order in self.orders.values()
            if order.advertiser_id == advertiser_id
        ]

    def list_with_contacts_before(self, cutoff: datetime) -> Iterable[Order]:
        """List orders with contacts_sent_at before cutoff."""

        return [
            order
            for order in self.orders.values()
            if order.contacts_sent_at and order.contacts_sent_at <= cutoff
        ]

    def count_by_advertiser(self, advertiser_id: UUID) -> int:
        """Count orders by advertiser."""

        return len(
            [
                order
                for order in self.orders.values()
                if order.advertiser_id == advertiser_id
            ]
        )

    def save(self, order: Order) -> None:
        """Persist order in memory."""

        self.orders[order.order_id] = order


@dataclass
class InMemoryOrderResponseRepository(OrderResponseRepository):
    """In-memory implementation of order response repository."""

    responses: list[OrderResponse] = field(default_factory=list)

    def save(self, response: OrderResponse) -> None:
        """Persist order response."""

        self.responses.append(response)

    def list_by_order(self, order_id: UUID) -> list[OrderResponse]:
        """List responses by order."""

        return [resp for resp in self.responses if resp.order_id == order_id]

    def exists(self, order_id: UUID, blogger_id: UUID) -> bool:
        """Check if blogger already responded."""

        return any(
            resp.order_id == order_id and resp.blogger_id == blogger_id
            for resp in self.responses
        )

    def count_by_order(self, order_id: UUID) -> int:
        """Count responses by order."""

        return len([resp for resp in self.responses if resp.order_id == order_id])


@dataclass
class InMemoryInteractionRepository(InteractionRepository):
    """In-memory implementation of interaction repository."""

    interactions: Dict[UUID, Interaction] = field(default_factory=dict)

    def get_by_id(self, interaction_id: UUID) -> Optional[Interaction]:
        """Fetch interaction by id."""

        return self.interactions.get(interaction_id)

    def get_by_participants(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

        for item in self.interactions.values():
            if (
                item.order_id == order_id
                and item.blogger_id == blogger_id
                and item.advertiser_id == advertiser_id
            ):
                return item
        return None

    def list_by_order(self, order_id: UUID) -> Iterable[Interaction]:
        """List interactions for order."""

        return [
            item for item in self.interactions.values() if item.order_id == order_id
        ]

    def list_due_for_feedback(self, cutoff: datetime) -> Iterable[Interaction]:
        """List interactions due for feedback."""

        return [
            item
            for item in self.interactions.values()
            if item.next_check_at is not None
            and item.next_check_at <= cutoff
            and item.status == InteractionStatus.PENDING
        ]

    def list_by_status(self, status: InteractionStatus) -> Iterable[Interaction]:
        """List interactions by status."""

        return [item for item in self.interactions.values() if item.status == status]

    def save(self, interaction: Interaction) -> None:
        """Persist interaction in memory."""

        self.interactions[interaction.interaction_id] = interaction


@dataclass
class InMemoryPaymentRepository(PaymentRepository):
    """In-memory implementation of payment repository."""

    payments: Dict[UUID, Payment] = field(default_factory=dict)

    def get_by_order(self, order_id: UUID) -> Optional[Payment]:
        """Fetch payment by order id."""

        for payment in self.payments.values():
            if payment.order_id == order_id:
                return payment
        return None

    def get_by_external_id(self, external_id: str) -> Optional[Payment]:
        """Fetch payment by provider external id."""

        for payment in self.payments.values():
            if payment.external_id == external_id:
                return payment
        return None

    def save(self, payment: Payment, session: object | None = None) -> None:
        """Persist payment in memory."""

        self.payments[payment.payment_id] = payment


@dataclass
class InMemoryContactPricingRepository(ContactPricingRepository):
    """In-memory contact pricing repository."""

    prices: Dict[int, ContactPricing] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize with default prices."""

        if not self.prices:
            now = datetime.now(timezone.utc)
            self.prices = {
                3: ContactPricing(bloggers_count=3, price=0.0, updated_at=now),
                10: ContactPricing(bloggers_count=10, price=0.0, updated_at=now),
                20: ContactPricing(bloggers_count=20, price=0.0, updated_at=now),
                30: ContactPricing(bloggers_count=30, price=0.0, updated_at=now),
                50: ContactPricing(bloggers_count=50, price=0.0, updated_at=now),
            }

    def get_by_bloggers_count(self, bloggers_count: int) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""

        return self.prices.get(bloggers_count)

    def save(self, pricing: ContactPricing) -> None:
        """Persist pricing in memory."""

        self.prices[pricing.bloggers_count] = pricing


@dataclass
class InMemoryOutboxRepository(OutboxRepository):
    """In-memory outbox repository."""

    events: Dict[UUID, OutboxEvent] = field(default_factory=dict)

    def save(self, event: OutboxEvent, session: object | None = None) -> None:
        """Persist outbox event."""

        self.events[event.event_id] = event

    def get_pending_events(self, limit: int = 100) -> List[OutboxEvent]:
        """Get pending events for processing."""

        pending_events = [
            event
            for event in self.events.values()
            if event.status == OutboxEventStatus.PENDING
        ]
        return sorted(pending_events, key=lambda e: e.created_at)[:limit]

    def mark_as_processing(self, event_id: UUID) -> None:
        """Mark event as processing."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = OutboxEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                payload=event.payload,
                status=OutboxEventStatus.PROCESSING,
                created_at=event.created_at,
                processed_at=event.processed_at,
                retry_count=event.retry_count,
                last_error=event.last_error,
            )

    def mark_as_published(self, event_id: UUID, processed_at: datetime) -> None:
        """Mark event as published."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = OutboxEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                payload=event.payload,
                status=OutboxEventStatus.PUBLISHED,
                created_at=event.created_at,
                processed_at=processed_at,
                retry_count=event.retry_count,
                last_error=event.last_error,
            )

    def mark_as_failed(self, event_id: UUID, error: str, retry_count: int) -> None:
        """Mark event as failed with retry."""

        if event_id in self.events:
            event = self.events[event_id]
            self.events[event_id] = OutboxEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                aggregate_type=event.aggregate_type,
                payload=event.payload,
                status=OutboxEventStatus.FAILED,
                created_at=event.created_at,
                processed_at=event.processed_at,
                retry_count=retry_count,
                last_error=error,
            )

    def get_by_id(self, event_id: UUID) -> Optional[OutboxEvent]:
        """Get event by ID."""

        return self.events.get(event_id)


@dataclass
class InMemoryComplaintRepository(ComplaintRepository):
    """In-memory implementation of complaint repository."""

    complaints: Dict[UUID, Complaint] = field(default_factory=dict)

    def save(self, complaint: Complaint) -> None:
        """Persist complaint."""

        self.complaints[complaint.complaint_id] = complaint

    def get_by_id(self, complaint_id: UUID) -> Optional[Complaint]:
        """Get complaint by ID."""

        return self.complaints.get(complaint_id)

    def list_by_order(self, order_id: UUID) -> Iterable[Complaint]:
        """List complaints for a specific order."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.order_id == order_id
        ]

    def list_by_reporter(self, reporter_id: UUID) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.reporter_id == reporter_id
        ]

    def exists(self, order_id: UUID, reporter_id: UUID) -> bool:
        """Check if reporter already filed a complaint for this order."""

        return any(
            complaint.order_id == order_id and complaint.reporter_id == reporter_id
            for complaint in self.complaints.values()
        )

    def list_by_status(self, status: ComplaintStatus) -> Iterable[Complaint]:
        """List complaints by status."""

        return [
            complaint
            for complaint in self.complaints.values()
            if complaint.status == status
        ]


@dataclass
class NoopOfferBroadcaster(OfferBroadcaster):
    """No-op broadcaster for MVP."""

    def broadcast_order(self, order: Order) -> None:
        """No-op implementation."""

        return None
