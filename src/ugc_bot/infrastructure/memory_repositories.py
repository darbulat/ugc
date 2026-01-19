"""In-memory repository implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Tuple
from uuid import UUID

from datetime import datetime, timezone

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    InstagramVerificationRepository,
    OfferBroadcaster,
    OrderRepository,
    OrderResponseRepository,
    PaymentRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    InstagramVerificationCode,
    Order,
    OrderResponse,
    Payment,
    User,
)
from ugc_bot.domain.enums import MessengerType, OrderStatus


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

    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile in memory."""

        self.profiles[profile.user_id] = profile

    def list_confirmed_user_ids(self) -> list[UUID]:
        """List confirmed blogger user ids."""

        return [
            profile.user_id for profile in self.profiles.values() if profile.confirmed
        ]

    def list_confirmed_profiles(self) -> list[BloggerProfile]:
        """List confirmed blogger profiles."""

        return [profile for profile in self.profiles.values() if profile.confirmed]


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
class InMemoryPaymentRepository(PaymentRepository):
    """In-memory implementation of payment repository."""

    payments: Dict[UUID, Payment] = field(default_factory=dict)

    def get_by_order(self, order_id: UUID) -> Optional[Payment]:
        """Fetch payment by order id."""

        for payment in self.payments.values():
            if payment.order_id == order_id:
                return payment
        return None

    def save(self, payment: Payment) -> None:
        """Persist payment in memory."""

        self.payments[payment.payment_id] = payment


@dataclass
class NoopOfferBroadcaster(OfferBroadcaster):
    """No-op broadcaster for MVP."""

    def broadcast_order(self, order: Order) -> None:
        """No-op implementation."""

        return None
