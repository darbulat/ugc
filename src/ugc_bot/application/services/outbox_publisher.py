"""Outbox publisher service for reliable event publishing."""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.ports import (
    OrderActivationPublisher,
    OrderRepository,
    OutboxRepository,
    TransactionManager,
)
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.domain.entities import Order, OutboxEvent
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


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
    financial_delivery: "OutboxPublisher | None" = None
    financial_router: FinancialEventRouter | None = None
    dispatch_control: Any = None

    async def publish_order_activation(
        self, order: Order, session: object | None = None
    ) -> None:
        """Publish order activation event to outbox."""

        async def publish(sess: object | None) -> None:
            if self.dispatch_control is None:
                await self._enqueue_activation(order, session=sess)
                return
            run = await self.dispatch_control.start(
                order.order_id, session=sess
            )
            if run is not None:
                await self._enqueue_activation(order, run=run, session=sess)

        if session is None and self.dispatch_control is not None:
            await with_optional_tx(self.transaction_manager, publish)
        else:
            await publish(session)

    async def resume_order_dispatch(
        self, order: Order, run: int, *, session: object
    ) -> None:
        await self._enqueue_activation(order, run=run, session=session)

    async def _enqueue_activation(
        self, order: Order, *, run: int | None = None, session: object | None
    ) -> None:
        event = self._create_event_from_order(order)
        if run is not None:
            event.payload["dispatch_run"] = run
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

    async def _reset_stale_events(self, stale_after_minutes: int = 15) -> None:
        """Reset stale PROCESSING events back to PENDING."""

        async def _run(session: object | None) -> None:
            count = await self.outbox_repo.reset_stale_processing_events(
                stale_after_minutes=stale_after_minutes, session=session
            )
            if count > 0:
                logger.warning(
                    "Reset %d stale PROCESSING outbox events to PENDING", count
                )

        await with_optional_tx(self.transaction_manager, _run)

    async def process_pending_events(
        self,
        kafka_publisher: OrderActivationPublisher | None,
        max_retries: int = 3,
        batch_limit: int = 100,
        concurrency: int = 10,
    ) -> None:
        """Process pending events (claim atomically, retry on failure).

        concurrency must not exceed the DB connection pool capacity
        (pool_size + max_overflow, default 15).
        """

        # A financial-only worker must not acquire or retry legacy deliveries.
        if kafka_publisher is None and self.financial_router is None:
            if self.financial_delivery is not None:
                await self.financial_delivery.process_pending_events(
                    None, max_retries, batch_limit, concurrency
                )
            return
        await self._reset_stale_events()

        async def _claim(session: object | None):
            return await self.outbox_repo.claim_pending_events(
                limit=batch_limit, session=session
            )

        claimed_events = await with_optional_tx(
            self.transaction_manager, _claim
        )

        sem = asyncio.Semaphore(concurrency)

        async def _handle(event: OutboxEvent) -> None:
            async with sem:
                if event.retry_count >= max_retries:
                    await self._mark_failed(
                        event.event_id,
                        f"Max retries ({max_retries}) exceeded",
                        event.retry_count,
                    )
                    return
                try:
                    await self._process_one_event(
                        event, kafka_publisher, max_retries
                    )
                except Exception as e:
                    next_retry = event.retry_count + 1
                    if next_retry >= max_retries:
                        await self._mark_failed(
                            event.event_id, str(e), next_retry
                        )
                    else:
                        await self._mark_for_retry(
                            event.event_id, str(e), next_retry
                        )

        await asyncio.gather(*[_handle(ev) for ev in claimed_events])
        if self.financial_delivery is not None:
            await self.financial_delivery.process_pending_events(
                kafka_publisher, max_retries, batch_limit, concurrency
            )

    async def _mark_failed(
        self, event_id: UUID, error: str, retry_count: int
    ) -> None:
        """Mark event as failed (terminal) within a transaction."""

        async def _run(session: object | None) -> None:
            await self.outbox_repo.mark_as_failed(
                event_id, error, retry_count, session=session
            )

        await with_optional_tx(self.transaction_manager, _run)

    async def _mark_for_retry(
        self, event_id: UUID, error: str, retry_count: int
    ) -> None:
        """Mark event for retry (back to PENDING) within a transaction."""

        async def _run(session: object | None) -> None:
            await self.outbox_repo.mark_for_retry(
                event_id, error, retry_count, session=session
            )

        await with_optional_tx(self.transaction_manager, _run)

    async def _process_one_event(
        self,
        event: OutboxEvent,
        kafka_publisher: OrderActivationPublisher | None,
        max_retries: int,
    ) -> None:
        """Process a single event in one transaction."""

        async def _run(session: object | None) -> None:
            await self.outbox_repo.mark_as_processing(
                event.event_id, session=session
            )
            if self.financial_router is not None:
                await self.financial_router.route(event, session=session)
            elif event.event_type == "order.activated":
                if kafka_publisher is None:
                    raise ValueError("order_activation_publisher_unavailable")
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

        run = event.payload.get("dispatch_run")
        if run is not None:
            if (
                order.status == OrderStatus.ACTIVE
                and not order.dispatch_stopped
            ):
                await kafka_publisher.publish(order, dispatch_run=run)
            return

        activated_order = replace(order, status=OrderStatus.ACTIVE)
        await self.order_repo.save(activated_order, session=session)

        await kafka_publisher.publish(activated_order)

    async def cleanup_processed_events(
        self, retention_days: int, batch_size: int
    ) -> int:
        """Delete PUBLISHED/FAILED events older than retention_days.

        Returns deleted count.
        """

        async def _run(session: object | None) -> int:
            return await self.outbox_repo.delete_processed_events(
                retention_days, batch_size, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)
