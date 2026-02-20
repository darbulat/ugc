"""Service for Telegram payments and order activation."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    ContactPricingRepository,
    OrderRepository,
    PaymentRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import Order, Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PaymentService:
    """Telegram payment service. Moves order to PENDING_MODERATION."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    pricing_repo: ContactPricingRepository
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

        if self.transaction_manager is None:
            raise ValueError(
                "PaymentService needs transaction_manager for atomic payment."
            )

        return await self._confirm_telegram_payment_impl(
            user_id,
            order_id,
            provider_payment_charge_id,
            total_amount,
            currency,
        )

    async def get_order(self, order_id: UUID) -> Order | None:
        """Fetch order by id within a transaction boundary."""

        async def _run(session: object | None):
            return await self.order_repo.get_by_id(order_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def _confirm_telegram_payment_impl(
        self,
        user_id: UUID,
        order_id: UUID,
        provider_payment_charge_id: str,
        total_amount: int,
        currency: str,
    ) -> Payment:
        """Confirm payment (assumes transaction_manager is set)."""

        assert self.transaction_manager is not None
        async with self.transaction_manager.transaction() as session:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError("Advertiser not found.")
            if (
                await self.advertiser_repo.get_by_user_id(
                    user_id, session=session
                )
                is None
            ):
                raise OrderCreationError("Advertiser profile is not set.")

            order = await self.order_repo.get_by_id(order_id, session=session)
            if order is None:
                raise OrderCreationError("Order not found.")
            if order.advertiser_id != user_id:
                raise OrderCreationError("Order does not belong to advertiser.")

            if order.status != OrderStatus.NEW:
                raise OrderCreationError("Order is not in NEW status.")

            existing = await self.payment_repo.get_by_order(
                order_id, session=session
            )
            if existing and existing.status == PaymentStatus.PAID:
                return existing

            pricing = await self.pricing_repo.get_by_bloggers_count(
                order.bloggers_needed, session=session
            )
            if pricing is None:
                raise OrderCreationError(
                    "Contact pricing not configured for this bloggers count."
                )
            expected_amount_minor = round(pricing.price * 100)
            if total_amount != expected_amount_minor:
                raise OrderCreationError(
                    "Payment amount does not match order price."
                )

            now = datetime.now(timezone.utc)
            if existing is not None:
                payment = replace(
                    existing,
                    status=PaymentStatus.PAID,
                    amount=round(total_amount / 100, 2),
                    currency=currency,
                    external_id=provider_payment_charge_id,
                    paid_at=now,
                    updated_at=now,
                )
            else:
                payment = Payment(
                    payment_id=uuid4(),
                    order_id=order_id,
                    provider=self.provider,
                    status=PaymentStatus.PAID,
                    amount=round(total_amount / 100, 2),
                    currency=currency,
                    external_id=provider_payment_charge_id,
                    created_at=now,
                    paid_at=now,
                )
            await self.payment_repo.save(payment, session=session)
            order_pending = replace(
                order, status=OrderStatus.PENDING_MODERATION
            )
            await self.order_repo.save(order_pending, session=session)

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
