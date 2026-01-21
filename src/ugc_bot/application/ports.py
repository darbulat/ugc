"""Repository ports for the application layer."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, List, Optional
from uuid import UUID

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
from ugc_bot.domain.enums import MessengerType

if TYPE_CHECKING:
    from ugc_bot.domain.enums import ComplaintStatus, InteractionStatus


class UserRepository(ABC):
    """Port for user persistence."""

    @abstractmethod
    def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Fetch a user by ID."""

    @abstractmethod
    def get_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

    @abstractmethod
    def save(self, user: User) -> None:
        """Persist a user."""

    def iter_all(self) -> Iterable[User]:
        """Iterate all users (optional)."""

        raise NotImplementedError


class BloggerProfileRepository(ABC):
    """Port for blogger profile persistence."""

    @abstractmethod
    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

    @abstractmethod
    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile."""

    @abstractmethod
    def list_confirmed_user_ids(self) -> list[UUID]:
        """List user ids with confirmed blogger profiles."""


class AdvertiserProfileRepository(ABC):
    """Port for advertiser profile persistence."""

    @abstractmethod
    def get_by_user_id(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

    @abstractmethod
    def save(self, profile: AdvertiserProfile) -> None:
        """Persist advertiser profile."""


class OrderRepository(ABC):
    """Port for order persistence."""

    @abstractmethod
    def get_by_id(self, order_id: UUID) -> Optional[Order]:
        """Fetch order by ID."""

    @abstractmethod
    def list_active(self) -> Iterable[Order]:
        """List active orders."""

    @abstractmethod
    def list_by_advertiser(self, advertiser_id: UUID) -> Iterable[Order]:
        """List orders by advertiser."""

    @abstractmethod
    def list_with_contacts_before(self, cutoff: datetime) -> Iterable[Order]:
        """List orders with contacts_sent_at before cutoff."""

    @abstractmethod
    def count_by_advertiser(self, advertiser_id: UUID) -> int:
        """Count orders by advertiser."""

    @abstractmethod
    def save(self, order: Order) -> None:
        """Persist order."""


class OrderResponseRepository(ABC):
    """Port for order response persistence."""

    @abstractmethod
    def save(self, response: OrderResponse) -> None:
        """Persist order response."""

    @abstractmethod
    def list_by_order(self, order_id: UUID) -> Iterable[OrderResponse]:
        """List responses by order."""

    @abstractmethod
    def exists(self, order_id: UUID, blogger_id: UUID) -> bool:
        """Check if blogger already responded."""

    @abstractmethod
    def count_by_order(self, order_id: UUID) -> int:
        """Count responses by order."""


class InteractionRepository(ABC):
    """Port for interaction persistence."""

    @abstractmethod
    def get_by_id(self, interaction_id: UUID) -> Optional[Interaction]:
        """Fetch interaction by id."""

    @abstractmethod
    def get_by_participants(
        self, order_id: UUID, blogger_id: UUID, advertiser_id: UUID
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

    @abstractmethod
    def list_by_order(self, order_id: UUID) -> Iterable[Interaction]:
        """List interactions for order."""

    @abstractmethod
    def list_due_for_feedback(self, cutoff: datetime) -> Iterable[Interaction]:
        """List interactions due for feedback (next_check_at <= cutoff and status=PENDING)."""

    @abstractmethod
    def list_by_status(self, status: "InteractionStatus") -> Iterable[Interaction]:
        """List interactions by status."""

    @abstractmethod
    def save(self, interaction: Interaction) -> None:
        """Persist interaction."""


class InstagramVerificationRepository(ABC):
    """Port for Instagram verification code persistence."""

    @abstractmethod
    def save(self, code: InstagramVerificationCode) -> None:
        """Persist verification code."""

    @abstractmethod
    def get_valid_code(
        self, user_id: UUID, code: str
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

    @abstractmethod
    def mark_used(self, code_id: UUID) -> None:
        """Mark verification code as used."""


class PaymentRepository(ABC):
    """Port for payment persistence."""

    @abstractmethod
    def get_by_order(self, order_id: UUID) -> Optional[Payment]:
        """Fetch payment by order id."""

    @abstractmethod
    def get_by_external_id(self, external_id: str) -> Optional[Payment]:
        """Fetch payment by provider external id."""

    @abstractmethod
    def save(self, payment: Payment) -> None:
        """Persist payment."""


class ContactPricingRepository(ABC):
    """Port for contact pricing persistence."""

    @abstractmethod
    def get_by_bloggers_count(self, bloggers_count: int) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""


class OfferBroadcaster(ABC):
    """Port for broadcasting offers to bloggers."""

    @abstractmethod
    def broadcast_order(self, order: Order) -> None:
        """Broadcast offer to eligible bloggers."""


class OrderActivationPublisher(ABC):
    """Port for publishing order activation events."""

    @abstractmethod
    def publish(self, order: Order) -> None:
        """Publish order activation message."""


class OutboxRepository(ABC):
    """Port for outbox event persistence."""

    @abstractmethod
    def save(self, event: OutboxEvent) -> None:
        """Persist outbox event."""

    @abstractmethod
    def get_pending_events(self, limit: int = 100) -> List[OutboxEvent]:
        """Get pending events for processing."""

    @abstractmethod
    def mark_as_processing(self, event_id: UUID) -> None:
        """Mark event as processing."""

    @abstractmethod
    def mark_as_published(self, event_id: UUID, processed_at: datetime) -> None:
        """Mark event as published."""

    @abstractmethod
    def mark_as_failed(self, event_id: UUID, error: str, retry_count: int) -> None:
        """Mark event as failed with retry."""

    @abstractmethod
    def get_by_id(self, event_id: UUID) -> Optional[OutboxEvent]:
        """Get event by ID."""


class ComplaintRepository(ABC):
    """Port for complaint persistence."""

    @abstractmethod
    def save(self, complaint: Complaint) -> None:
        """Persist complaint."""

    @abstractmethod
    def get_by_id(self, complaint_id: UUID) -> Optional[Complaint]:
        """Get complaint by ID."""

    @abstractmethod
    def list_by_order(self, order_id: UUID) -> Iterable[Complaint]:
        """List complaints for a specific order."""

    @abstractmethod
    def list_by_reporter(self, reporter_id: UUID) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

    @abstractmethod
    def exists(self, order_id: UUID, reporter_id: UUID) -> bool:
        """Check if reporter already filed a complaint for this order."""

    @abstractmethod
    def list_by_status(self, status: "ComplaintStatus") -> Iterable[Complaint]:
        """List complaints by status."""
