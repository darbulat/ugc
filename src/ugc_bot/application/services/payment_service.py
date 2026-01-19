"""Service for mock payments and order activation."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    OfferBroadcaster,
    OrderActivationPublisher,
    OrderRepository,
    PaymentRepository,
    UserRepository,
)
from ugc_bot.domain.entities import Order, Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus


@dataclass(slots=True)
class PaymentService:
    """Mock payment service for activating orders."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    broadcaster: OfferBroadcaster
    activation_publisher: OrderActivationPublisher

    def mock_pay(self, user_id: UUID, order_id: UUID) -> Payment:
        """Mock payment for a specific order."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("Advertiser not found.")
        if self.advertiser_repo.get_by_user_id(user_id) is None:
            raise OrderCreationError("Advertiser profile is not set.")

        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.advertiser_id != user_id:
            raise OrderCreationError("Order does not belong to advertiser.")

        existing = self.payment_repo.get_by_order(order_id)
        if existing and existing.status == PaymentStatus.PAID:
            return existing

        if order.status != OrderStatus.NEW:
            raise OrderCreationError("Order is not in NEW status.")

        now = datetime.now(timezone.utc)
        payment = Payment(
            payment_id=uuid4(),
            order_id=order_id,
            provider="mock",
            status=PaymentStatus.PAID,
            amount=order.price,
            currency="RUB",
            external_id=f"mock:{order_id}",
            created_at=now,
            paid_at=now,
        )
        self.payment_repo.save(payment)

        activated = Order(
            order_id=order.order_id,
            advertiser_id=order.advertiser_id,
            product_link=order.product_link,
            offer_text=order.offer_text,
            ugc_requirements=order.ugc_requirements,
            barter_description=order.barter_description,
            price=order.price,
            bloggers_needed=order.bloggers_needed,
            status=OrderStatus.ACTIVE,
            created_at=order.created_at,
            contacts_sent_at=order.contacts_sent_at,
        )
        self.order_repo.save(activated)
        self.broadcaster.broadcast_order(activated)
        self.activation_publisher.publish(activated)
        return payment
