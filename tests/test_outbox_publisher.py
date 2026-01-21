"""Tests for outbox publisher."""

from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID

from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.entities import Order, OutboxEvent
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus


class TestOutboxPublisher:
    """Test outbox publisher."""

    def test_publish_order_activation(self) -> None:
        """Event is saved to outbox when publishing order activation."""

        outbox_repo = Mock()
        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)

        order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000001"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000002"),
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )

        publisher.publish_order_activation(order)

        # Verify event was saved
        assert outbox_repo.save.called
        event = outbox_repo.save.call_args[0][0]

        assert isinstance(event, OutboxEvent)
        assert event.event_type == "order.activated"
        assert event.aggregate_id == str(order.order_id)
        assert event.aggregate_type == "order"
        assert event.status == OutboxEventStatus.PENDING
        assert event.payload == {
            "order_id": str(order.order_id),
            "advertiser_id": str(order.advertiser_id),
            "product_link": order.product_link,
            "offer_text": order.offer_text,
            "bloggers_needed": order.bloggers_needed,
            "price": order.price,
        }

    def test_process_pending_events_success(self) -> None:
        """Successful event processing marks as published."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        # Mock pending events
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        outbox_repo.get_pending_events.return_value = [event]

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was marked as processing
        outbox_repo.mark_as_processing.assert_called_once_with(event.event_id)

        # Verify event was published to Kafka
        kafka_publisher.publish.assert_called_once()

        # Verify event was marked as published
        outbox_repo.mark_as_published.assert_called_once()
        call_args = outbox_repo.mark_as_published.call_args
        assert call_args[0][0] == event.event_id
        assert isinstance(call_args[0][1], datetime)

    def test_process_pending_events_failure_then_success(self) -> None:
        """Failed event is retried and eventually succeeds."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        # Mock pending event
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=1,  # Already failed once
            last_error="Connection error",
        )

        outbox_repo.get_pending_events.return_value = [event]

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was marked as processing
        outbox_repo.mark_as_processing.assert_called_once_with(event.event_id)

        # Verify event was published to Kafka
        kafka_publisher.publish.assert_called_once()

        # Verify event was marked as published
        outbox_repo.mark_as_published.assert_called_once()
        call_args = outbox_repo.mark_as_published.call_args
        assert call_args[0][0] == event.event_id
        assert isinstance(call_args[0][1], datetime)

    def test_process_pending_events_permanent_failure(self) -> None:
        """Event with max retries is marked as permanently failed."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        # Mock pending event at max retries
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=3,  # At max retries
            last_error="Previous error",
        )

        outbox_repo.get_pending_events.return_value = [event]
        kafka_publisher.publish.side_effect = Exception("Kafka error")

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was NOT marked as processing (skipped due to max retries)
        outbox_repo.mark_as_processing.assert_not_called()

        # Verify event was NOT marked as published
        outbox_repo.mark_as_published.assert_not_called()

        # Verify event was marked as permanently failed
        outbox_repo.mark_as_failed.assert_called_once()
        call_args = outbox_repo.mark_as_failed.call_args[0]
        assert call_args[0] == event.event_id
        error_msg = call_args[1]
        retry_count = call_args[2]
        assert "Max retries (3) exceeded" in error_msg
        assert retry_count == 3

    def test_process_pending_events_temporary_failure(self) -> None:
        """Failed event is retried with incremented counter."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        # Mock pending event
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=1,
            last_error=None,
        )

        outbox_repo.get_pending_events.return_value = [event]
        kafka_publisher.publish.side_effect = Exception("Kafka temporarily unavailable")

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was marked as processing
        outbox_repo.mark_as_processing.assert_called_once_with(event.event_id)

        # Verify event was marked as failed with retry
        outbox_repo.mark_as_failed.assert_called_once_with(
            event.event_id,
            "Kafka temporarily unavailable",
            2,  # retry_count + 1
        )

        # Verify event was NOT marked as published
        outbox_repo.mark_as_published.assert_not_called()

    def test_process_pending_events_no_events(self) -> None:
        """No action when no pending events."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        outbox_repo.get_pending_events.return_value = []

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify no interactions with repositories
        outbox_repo.mark_as_processing.assert_not_called()
        outbox_repo.mark_as_published.assert_not_called()
        outbox_repo.mark_as_failed.assert_not_called()
        kafka_publisher.publish.assert_not_called()

    def test_process_pending_events_unknown_event_type(self) -> None:
        """Unknown event type causes failure."""

        outbox_repo = Mock()
        kafka_publisher = Mock()

        # Mock event with unknown type
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="unknown.event",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        outbox_repo.get_pending_events.return_value = [event]

        order_repo = Mock()
        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was marked as failed
        outbox_repo.mark_as_failed.assert_called_once()
        call_args = outbox_repo.mark_as_failed.call_args[0]
        error_msg = call_args[1]
        retry_count = call_args[2]
        assert "Unknown event type" in error_msg
        assert retry_count == 1

    def test_process_order_activation_order_not_found(self) -> None:
        """Event fails when order is not found."""

        outbox_repo = Mock()
        kafka_publisher = Mock()
        order_repo = Mock()

        # Mock order repository to return None
        order_repo.get_by_id.return_value = None

        # Mock pending event
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        outbox_repo.get_pending_events.return_value = [event]

        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify event was marked as failed
        outbox_repo.mark_as_failed.assert_called_once()
        call_args = outbox_repo.mark_as_failed.call_args[0]
        error_msg = call_args[1]
        retry_count = call_args[2]
        assert "Order" in error_msg and "not found" in error_msg
        assert retry_count == 1

        # Verify Kafka was NOT called
        kafka_publisher.publish.assert_not_called()

    def test_process_order_activation_kafka_failure(self) -> None:
        """Event fails when Kafka publish fails."""

        outbox_repo = Mock()
        kafka_publisher = Mock()
        order_repo = Mock()

        # Mock order repository to return order
        test_order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000001"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000002"),
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
        order_repo.get_by_id.return_value = test_order

        # Make Kafka publish raise an exception
        kafka_publisher.publish.side_effect = Exception("Kafka connection failed")

        # Mock pending event
        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="00000000-0000-0000-0000-000000000001",
            aggregate_type="order",
            payload={
                "order_id": "00000000-0000-0000-0000-000000000001",
                "advertiser_id": "00000000-0000-0000-0000-000000000002",
                "product_link": "https://example.com",
                "offer_text": "Test offer",
                "bloggers_needed": 3,
                "price": 1000.0,
            },
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        outbox_repo.get_pending_events.return_value = [event]

        publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
        publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify order was saved (activation happened before Kafka failure)
        order_repo.save.assert_called_once()

        # Verify event was marked as failed
        outbox_repo.mark_as_failed.assert_called_once()
        call_args = outbox_repo.mark_as_failed.call_args[0]
        error_msg = call_args[1]
        retry_count = call_args[2]
        assert "Kafka connection failed" in error_msg
        assert retry_count == 1
