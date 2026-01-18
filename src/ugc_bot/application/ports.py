"""Repository ports for the application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional
from uuid import UUID

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    InstagramVerificationCode,
    Interaction,
    Order,
    OrderResponse,
    Payment,
    User,
)
from ugc_bot.domain.enums import MessengerType


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


class BloggerProfileRepository(ABC):
    """Port for blogger profile persistence."""

    @abstractmethod
    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

    @abstractmethod
    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile."""


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


class InteractionRepository(ABC):
    """Port for interaction persistence."""

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
    def save(self, payment: Payment) -> None:
        """Persist payment."""


class OfferBroadcaster(ABC):
    """Port for broadcasting offers to bloggers."""

    @abstractmethod
    def broadcast_order(self, order: Order) -> None:
        """Broadcast offer to eligible bloggers."""


class ComplaintRepository(ABC):
    """Port for complaint persistence."""

    @abstractmethod
    def save(self, complaint: Complaint) -> None:
        """Persist complaint."""
