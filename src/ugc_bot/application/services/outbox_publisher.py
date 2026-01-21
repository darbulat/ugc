"""Outbox publisher service for reliable event publishing."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import (
    OrderActivationPublisher,
    OrderRepository,
    OutboxRepository,
)
from ugc_bot.domain.entities import Order, OutboxEvent
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus


@dataclass(slots=True)
class OutboxPublisher:
    """Service for publishing events via outbox pattern."""

    outbox_repo: OutboxRepository
    order_repo: OrderRepository

    def publish_order_activation(self, order: Order) -> None:
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
        self.outbox_repo.save(event)

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

    def process_pending_events(
        self, kafka_publisher: OrderActivationPublisher, max_retries: int = 3
    ) -> None:
        """Process pending events from outbox."""

        pending_events = self.outbox_repo.get_pending_events()

        for event in pending_events:
            if event.retry_count >= max_retries:
                # Mark as permanently failed
                self.outbox_repo.mark_as_failed(
                    event.event_id,
                    f"Max retries ({max_retries}) exceeded",
                    event.retry_count,
                )
                continue

            try:
                # Mark as processing
                self.outbox_repo.mark_as_processing(event.event_id)

                # Process the event based on type
                if event.event_type == "order.activated":
                    self._process_order_activation(event, kafka_publisher)
                else:
                    raise ValueError(f"Unknown event type: {event.event_type}")

                # Mark as published
                self.outbox_repo.mark_as_published(
                    event.event_id, datetime.now(timezone.utc)
                )

            except Exception as e:
                # Mark as failed and increment retry count
                self.outbox_repo.mark_as_failed(
                    event.event_id, str(e), event.retry_count + 1
                )

    def _process_order_activation(
        self, event: OutboxEvent, kafka_publisher: OrderActivationPublisher
    ) -> None:
        """Process order activation event."""

        # Get the order from repository
        order_id = UUID(event.payload["order_id"])
        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        # Activate the order
        activated_order = Order(
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
        self.order_repo.save(activated_order)

        # Publish to Kafka
        kafka_publisher.publish(activated_order)
