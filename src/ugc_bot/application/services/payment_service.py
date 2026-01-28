"""Service for Telegram payments and order activation."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    OfferBroadcaster,
    OrderRepository,
    PaymentRepository,
    UserRepository,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.entities import Order, Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus

logger = logging.getLogger(__name__)


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


@dataclass(slots=True)
class PaymentService:
    """Telegram payment service for activating orders."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    broadcaster: OfferBroadcaster
    outbox_publisher: OutboxPublisher
    provider: str = "yookassa_telegram"
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def confirm_telegram_payment(
        self,
        user_id: UUID,
        order_id: UUID,
        provider_payment_charge_id: str,
        total_amount: int,
        currency: str,
    ) -> Payment:
        """Confirm a Telegram payment and activate order."""

        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("Advertiser not found.")
        if await self.advertiser_repo.get_by_user_id(user_id) is None:
            raise OrderCreationError("Advertiser profile is not set.")

        order = await self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderCreationError("Order not found.")
        if order.advertiser_id != user_id:
            raise OrderCreationError("Order does not belong to advertiser.")

        if order.status != OrderStatus.NEW:
            raise OrderCreationError("Order is not in NEW status.")

        existing = await self.payment_repo.get_by_order(order_id)
        if existing and existing.status == PaymentStatus.PAID:
            return existing

        if self.transaction_manager is None:
            raise ValueError(
                "PaymentService requires transaction_manager for atomic payment+outbox."
            )

        now = datetime.now(timezone.utc)
        payment = Payment(
            payment_id=existing.payment_id if existing else uuid4(),
            order_id=order_id,
            provider=self.provider,
            status=PaymentStatus.PAID,
            amount=round(total_amount / 100, 2),
            currency=currency,
            external_id=provider_payment_charge_id,
            created_at=now,
            paid_at=now,
        )
        async with self.transaction_manager.transaction() as session:
            await self.payment_repo.save(payment, session=session)
            await self.outbox_publisher.publish_order_activation(order, session=session)

        logger.info(
            "Payment confirmed",
            extra={
                "payment_id": str(payment.payment_id),
                "order_id": str(order_id),
                "user_id": str(user_id),
                "amount": float(payment.amount),
                "currency": payment.currency,
                "external_id": payment.external_id,
                "event_type": "payment.confirmed",
            },
        )

        return payment

    async def _activate_order(self, order: Order) -> None:
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
        await self.order_repo.save(activated)
        await self.broadcaster.broadcast_order(activated)
        await self.outbox_publisher.publish_order_activation(activated)
