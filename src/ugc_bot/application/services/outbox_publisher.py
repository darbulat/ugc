"""Outbox publisher service for reliable event publishing."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from ugc_bot.application.ports import (
    OrderActivationPublisher,
    OrderRepository,
    OutboxRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import Order, OutboxEvent
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class OutboxPublisher:
    """Service for publishing events via outbox pattern.

    Two usage modes:

    1. Write-only (e.g. PaymentService): transaction_manager can be None.
       Caller passes session to publish_order_activation(order, session=session)
       in its own transaction. Event saved in same tx as payment.

    2. Read+process (e.g. outbox_processor): transaction_manager required.
       process_pending_events() manages transactions via with_optional_tx().
       No parent transaction—processor opens transactions itself.
    """

    outbox_repo: OutboxRepository
    order_repo: OrderRepository
    transaction_manager: Optional[TransactionManager] = None

    async def publish_order_activation(
        self, order: Order, session: object | None = None
    ) -> None:
        """Publish order activation event to outbox."""

        event = OutboxEvent(
            event_id=uuid4(),
            event_type="order.activated",
            aggregate_id=str(order.order_id),
            aggregate_type="order",
            payload={
                "order_id": str(order.order_id),
                "advertiser_id": str(order.advertiser_id),
                "product_link": order.product_link,
                "offer_text": order.offer_text,
                "bloggers_needed": order.bloggers_needed,
                "price": order.price,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )
        await self.outbox_repo.save(event, session=session)

    def _create_event_from_order(self, order: Order) -> OutboxEvent:
        """Create outbox event from order (for testing)."""
        return OutboxEvent(
            event_id=uuid4(),
            event_type="order.activated",
            aggregate_id=str(order.order_id),
            aggregate_type="order",
            payload={
                "order_id": str(order.order_id),
                "advertiser_id": str(order.advertiser_id),
                "product_link": order.product_link,
                "offer_text": order.offer_text,
                "bloggers_needed": order.bloggers_needed,
                "price": order.price,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

    async def process_pending_events(
        self, kafka_publisher: OrderActivationPublisher, max_retries: int = 3
    ) -> None:
        """Process pending events from outbox."""

        async def _fetch_pending(session: object | None):
            return await self.outbox_repo.get_pending_events(session=session)

        pending_events = await with_optional_tx(
            self.transaction_manager, _fetch_pending
        )

        for event in pending_events:
            if event.retry_count >= max_retries:
                await self._mark_failed(
                    event.event_id,
                    f"Max retries ({max_retries}) exceeded",
                    event.retry_count,
                )
                continue

            try:
                await self._process_one_event(
                    event, kafka_publisher, max_retries
                )
            except Exception as e:
                await self._mark_failed(
                    event.event_id, str(e), event.retry_count + 1
                )

    async def _mark_failed(
        self, event_id: UUID, error: str, retry_count: int
    ) -> None:
        """Mark event as failed within a transaction."""

        async def _run(session: object | None) -> None:
            await self.outbox_repo.mark_as_failed(
                event_id, error, retry_count, session=session
            )

        await with_optional_tx(self.transaction_manager, _run)

    async def _process_one_event(
        self,
        event: OutboxEvent,
        kafka_publisher: OrderActivationPublisher,
        max_retries: int,
    ) -> None:
        """Process a single event in one transaction."""

        async def _run(session: object | None) -> None:
            await self.outbox_repo.mark_as_processing(
                event.event_id, session=session
            )
            if event.event_type == "order.activated":
                await self._process_order_activation(
                    event, kafka_publisher, session=session
                )
            else:
                raise ValueError(f"Unknown event type: {event.event_type}")
            await self.outbox_repo.mark_as_published(
                event.event_id, datetime.now(timezone.utc), session=session
            )

        await with_optional_tx(self.transaction_manager, _run)

    async def _process_order_activation(
        self,
        event: OutboxEvent,
        kafka_publisher: OrderActivationPublisher,
        session: object | None = None,
    ) -> None:
        """Process order activation event."""

        order_id = UUID(event.payload["order_id"])
        order = await self.order_repo.get_by_id(order_id, session=session)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        activated_order = Order(
            order_id=order.order_id,
            advertiser_id=order.advertiser_id,
            order_type=order.order_type,
            product_link=order.product_link,
            offer_text=order.offer_text,
            barter_description=order.barter_description,
            price=order.price,
            bloggers_needed=order.bloggers_needed,
            status=OrderStatus.ACTIVE,
            created_at=order.created_at,
            completed_at=order.completed_at,
            content_usage=order.content_usage,
            deadlines=order.deadlines,
            geography=order.geography,
            product_photo_file_id=order.product_photo_file_id,
        )
        await self.order_repo.save(activated_order, session=session)

        await kafka_publisher.publish(activated_order)
