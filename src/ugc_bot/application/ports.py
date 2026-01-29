"""Repository ports for the application layer."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    AsyncContextManager,
    Iterable,
    List,
    Optional,
    Protocol,
)
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
    async def get_by_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[User]:
        """Fetch a user by ID."""

    @abstractmethod
    async def get_by_external(
        self,
        external_id: str,
        messenger_type: MessengerType,
        session: object | None = None,
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

    @abstractmethod
    async def save(self, user: User, session: object | None = None) -> None:
        """Persist a user."""

    async def iter_all(self) -> Iterable[User]:
        """Iterate all users (optional)."""

        raise NotImplementedError


class BloggerProfileRepository(ABC):
    """Port for blogger profile persistence."""

    @abstractmethod
    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

    @abstractmethod
    async def get_by_instagram_url(
        self, instagram_url: str, session: object | None = None
    ) -> Optional[BloggerProfile]:
        """Fetch blogger profile by Instagram URL."""

    @abstractmethod
    async def save(
        self, profile: BloggerProfile, session: object | None = None
    ) -> None:
        """Persist blogger profile."""

    @abstractmethod
    async def list_confirmed_user_ids(
        self, session: object | None = None
    ) -> list[UUID]:
        """List user ids with confirmed blogger profiles."""


class AdvertiserProfileRepository(ABC):
    """Port for advertiser profile persistence."""

    @abstractmethod
    async def get_by_user_id(
        self, user_id: UUID, session: object | None = None
    ) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

    @abstractmethod
    async def save(
        self, profile: AdvertiserProfile, session: object | None = None
    ) -> None:
        """Persist advertiser profile."""


class OrderRepository(ABC):
    """Port for order persistence."""

    @abstractmethod
    async def get_by_id(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID."""

    @abstractmethod
    async def get_by_id_for_update(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Order]:
        """Fetch order by ID with a row lock when supported."""

    @abstractmethod
    async def list_active(self, session: object | None = None) -> Iterable[Order]:
        """List active orders."""

    @abstractmethod
    async def list_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> Iterable[Order]:
        """List orders by advertiser."""

    @abstractmethod
    async def list_with_contacts_before(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Order]:
        """List orders with contacts_sent_at before cutoff."""

    @abstractmethod
    async def count_by_advertiser(
        self, advertiser_id: UUID, session: object | None = None
    ) -> int:
        """Count orders by advertiser."""

    @abstractmethod
    async def save(self, order: Order, session: object | None = None) -> None:
        """Persist order."""


class OrderResponseRepository(ABC):
    """Port for order response persistence."""

    @abstractmethod
    async def save(
        self, response: OrderResponse, session: object | None = None
    ) -> None:
        """Persist order response."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[OrderResponse]:
        """List responses by order."""

    @abstractmethod
    async def exists(
        self, order_id: UUID, blogger_id: UUID, session: object | None = None
    ) -> bool:
        """Check if blogger already responded."""

    @abstractmethod
    async def count_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> int:
        """Count responses by order."""


class InteractionRepository(ABC):
    """Port for interaction persistence."""

    @abstractmethod
    async def get_by_id(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[Interaction]:
        """Fetch interaction by id."""

    @abstractmethod
    async def get_by_participants(
        self,
        order_id: UUID,
        blogger_id: UUID,
        advertiser_id: UUID,
        session: object | None = None,
    ) -> Optional[Interaction]:
        """Fetch interaction by order/blogger/advertiser."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions for order."""

    @abstractmethod
    async def list_due_for_feedback(
        self, cutoff: datetime, session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions due for feedback (next_check_at <= cutoff and status=PENDING)."""

    @abstractmethod
    async def list_by_status(
        self, status: "InteractionStatus", session: object | None = None
    ) -> Iterable[Interaction]:
        """List interactions by status."""

    @abstractmethod
    async def save(
        self, interaction: Interaction, session: object | None = None
    ) -> None:
        """Persist interaction."""


class InstagramVerificationRepository(ABC):
    """Port for Instagram verification code persistence."""

    @abstractmethod
    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code."""

    @abstractmethod
    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

    @abstractmethod
    async def mark_used(self, code_id: UUID, session: object | None = None) -> None:
        """Mark verification code as used."""

    @abstractmethod
    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code by code string (for webhook processing)."""


class InstagramGraphApiClient(ABC):
    """Port for Instagram Graph API client."""

    @abstractmethod
    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID.

        Args:
            instagram_user_id: Instagram-scoped user ID (sender_id from webhook)

        Returns:
            Username if found, None otherwise
        """


class PaymentRepository(ABC):
    """Port for payment persistence."""

    @abstractmethod
    async def get_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by order id."""

    @abstractmethod
    async def get_by_external_id(
        self, external_id: str, session: object | None = None
    ) -> Optional[Payment]:
        """Fetch payment by provider external id."""

    @abstractmethod
    async def save(self, payment: Payment, session: object | None = None) -> None:
        """Persist payment."""


class ContactPricingRepository(ABC):
    """Port for contact pricing persistence."""

    @abstractmethod
    async def get_by_bloggers_count(
        self, bloggers_count: int, session: object | None = None
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count."""


class OfferBroadcaster(ABC):
    """Port for broadcasting offers to bloggers."""

    @abstractmethod
    async def broadcast_order(self, order: Order) -> None:
        """Broadcast offer to eligible bloggers."""


class OrderActivationPublisher(ABC):
    """Port for publishing order activation events."""

    @abstractmethod
    async def publish(self, order: Order) -> None:
        """Publish order activation message."""


class OutboxRepository(ABC):
    """Port for outbox event persistence."""

    @abstractmethod
    async def save(self, event: OutboxEvent, session: object | None = None) -> None:
        """Persist outbox event."""

    @abstractmethod
    async def get_pending_events(
        self, limit: int = 100, session: object | None = None
    ) -> List[OutboxEvent]:
        """Get pending events for processing."""

    @abstractmethod
    async def mark_as_processing(
        self, event_id: UUID, session: object | None = None
    ) -> None:
        """Mark event as processing."""

    @abstractmethod
    async def mark_as_published(
        self, event_id: UUID, processed_at: datetime, session: object | None = None
    ) -> None:
        """Mark event as published."""

    @abstractmethod
    async def mark_as_failed(
        self,
        event_id: UUID,
        error: str,
        retry_count: int,
        session: object | None = None,
    ) -> None:
        """Mark event as failed with retry."""

    @abstractmethod
    async def get_by_id(
        self, event_id: UUID, session: object | None = None
    ) -> Optional[OutboxEvent]:
        """Get event by ID."""


class ComplaintRepository(ABC):
    """Port for complaint persistence."""

    @abstractmethod
    async def save(self, complaint: Complaint, session: object | None = None) -> None:
        """Persist complaint."""

    @abstractmethod
    async def get_by_id(
        self, complaint_id: UUID, session: object | None = None
    ) -> Optional[Complaint]:
        """Get complaint by ID."""

    @abstractmethod
    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints for a specific order."""

    @abstractmethod
    async def list_by_reporter(
        self, reporter_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""

    @abstractmethod
    async def exists(
        self, order_id: UUID, reporter_id: UUID, session: object | None = None
    ) -> bool:
        """Check if reporter already filed a complaint for this order."""

    @abstractmethod
    async def list_by_status(
        self, status: "ComplaintStatus", session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints by status."""


class TransactionManager(Protocol):
    """Protocol for transaction handling used by application services.

    Services receive a TransactionManager that provides a session via
    async with tm.transaction() as session. The implementation (e.g.
    SessionTransactionManager in infrastructure) commits on success and
    rolls back on exception. This is the primary contract used by the
    application layer; UnitOfWork below is an alternative style.
    """

    def transaction(self) -> AsyncContextManager[object]:
        """Return an async context manager yielding a session.

        Use: async with tm.transaction() as session: ...
        """


class UnitOfWork(Protocol):
    """Alternative unit-of-work contract (session, commit, rollback).

    Not used by current services; they use TransactionManager with
    transaction() context manager instead.
    """

    session: object

    async def commit(self) -> None:
        """Commit the active transaction."""

    async def rollback(self) -> None:
        """Rollback the active transaction."""
