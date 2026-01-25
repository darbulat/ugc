"""Integration tests for outbox functionality."""

from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import Order, OutboxEvent, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OutboxEventStatus,
    UserRole,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)


class MockKafkaPublisher:
    """Mock Kafka publisher for testing."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.published_events = []

    def publish(self, order):
        """Mock publish method."""
        if self.should_fail:
            raise Exception("Mock failure")
        self.published_events.append(order)
        return order  # Return the order as if it was processed


class TestOutboxIntegration:
    """Integration tests for outbox functionality."""

    def test_payment_service_creates_outbox_event_on_activation(self) -> None:
        """Payment service creates outbox event when order is activated."""

        # Setup repositories
        user_repo = InMemoryUserRepository()
        order_repo = InMemoryOrderRepository()
        payment_repo = InMemoryPaymentRepository()
        outbox_repo = InMemoryOutboxRepository()

        # Setup user and profile
        user = User(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            role=UserRole.ADVERTISER,
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            instagram_url=None,
            confirmed=False,
            topics=None,
            audience_gender=None,
            audience_age_min=None,
            audience_age_max=None,
            audience_geo=None,
            price=None,
            contact="test@example.com",
            profile_updated_at=None,
        )
        user_repo.save(user)

        # Setup order
        order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000002"),
            advertiser_id=user.user_id,
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
        order_repo.save(order)

        # Don't create payment upfront - let confirm_telegram_payment create it
        # This ensures the outbox event is created

        # Create services
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )
        payment_service = PaymentService(
            user_repo=user_repo,
            order_repo=order_repo,
            payment_repo=payment_repo,
            broadcaster=NoopOfferBroadcaster(),
            outbox_publisher=outbox_publisher,
        )

        # Confirm payment (this should create outbox event)
        result = payment_service.confirm_telegram_payment(
            user_id=user.user_id,
            order_id=order.order_id,
            provider_payment_charge_id="test_charge_123",
            total_amount=100000,  # 1000.00 RUB in minor units
            currency="RUB",
        )

        # Verify payment was returned
        assert result is not None
        assert result.order_id == order.order_id

        # Verify order was NOT activated yet (activation happens via outbox)
        updated_order = order_repo.get_by_id(order.order_id)
        assert updated_order is not None
        assert (
            updated_order.status == OrderStatus.NEW
        )  # Still NEW until outbox is processed

        # Verify outbox event was created
        outbox_events = outbox_repo.get_pending_events()
        assert len(outbox_events) == 1

        event = outbox_events[0]
        assert event.event_type == "order.activated"
        assert event.aggregate_id == str(order.order_id)
        assert event.aggregate_type == "order"
        assert event.status == OutboxEventStatus.PENDING
        assert event.payload["order_id"] == str(order.order_id)
        assert event.payload["advertiser_id"] == str(user.user_id)
        assert event.payload["product_link"] == order.product_link
        assert event.payload["offer_text"] == order.offer_text
        assert event.payload["bloggers_needed"] == order.bloggers_needed
        assert event.payload["price"] == order.price

    def test_outbox_publisher_processes_event_successfully(self) -> None:
        """Outbox publisher successfully processes pending event."""

        # Setup repositories
        outbox_repo = InMemoryOutboxRepository()
        order_repo = InMemoryOrderRepository()

        # Create outbox publisher
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )

        # Create mock Kafka publisher
        kafka_publisher = MockKafkaPublisher()

        # Create event by publishing order activation (order starts as NEW)
        test_order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000001"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000002"),
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,  # Start as NEW
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
        outbox_publisher.publish_order_activation(test_order)

        # Save the order in repository so it can be found during processing
        order_repo.save(test_order)

        # Process events
        outbox_publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Get the processed event
        pending_events = outbox_repo.get_pending_events()
        assert len(pending_events) == 0  # Should be processed
        published_events = [
            e
            for e in outbox_repo.events.values()
            if e.status == OutboxEventStatus.PUBLISHED
        ]
        assert len(published_events) == 1
        updated_event = published_events[0]
        assert updated_event is not None
        assert updated_event.status == OutboxEventStatus.PUBLISHED
        assert updated_event.processed_at is not None

        # Verify Kafka was called
        assert len(kafka_publisher.published_events) == 1
        published_order = kafka_publisher.published_events[0]
        assert published_order.order_id == UUID("00000000-0000-0000-0000-000000000001")

    def test_outbox_publisher_handles_processing_failure(self) -> None:
        """Outbox publisher handles processing failure with retries."""

        # Setup repositories
        outbox_repo = InMemoryOutboxRepository()
        order_repo = InMemoryOrderRepository()

        # Create outbox publisher
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )

        # Create mock Kafka publisher that fails
        kafka_publisher = MockKafkaPublisher(should_fail=True)

        # Create event by publishing order activation
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
        outbox_publisher.publish_order_activation(test_order)

        # Save the order in repository so it can be found during processing
        order_repo.save(test_order)

        # Process events (should fail and retry)
        outbox_publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Get the failed event
        failed_events = [
            e
            for e in outbox_repo.events.values()
            if e.status == OutboxEventStatus.FAILED
        ]
        assert len(failed_events) == 1
        updated_event = failed_events[0]
        assert updated_event is not None
        assert updated_event.status == OutboxEventStatus.FAILED
        assert updated_event.retry_count == 1
        assert "Mock failure" in updated_event.last_error

    def test_outbox_publisher_handles_max_retries_exceeded(self) -> None:
        """Outbox publisher marks event as permanently failed after max retries."""

        # Setup repositories
        outbox_repo = InMemoryOutboxRepository()
        order_repo = InMemoryOrderRepository()

        # Create outbox publisher
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )

        # Create mock Kafka publisher that fails
        kafka_publisher = MockKafkaPublisher(should_fail=True)

        # Create event by publishing order activation
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
        outbox_publisher.publish_order_activation(test_order)

        # Manually set retry count to max for the created event
        pending_events = outbox_repo.get_pending_events()
        assert len(pending_events) == 1
        event = pending_events[0]
        # Create a new event with updated retry count (since it's frozen)
        updated_event = OutboxEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            payload=event.payload,
            status=event.status,
            created_at=event.created_at,
            processed_at=event.processed_at,
            retry_count=3,  # Set to max retries
            last_error=event.last_error,
        )
        outbox_repo.save(updated_event)

        # Save the order in repository so it can be found during processing
        order_repo.save(test_order)

        # Process events (should mark as permanently failed)
        outbox_publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Get the permanently failed event
        failed_events = [
            e
            for e in outbox_repo.events.values()
            if e.status == OutboxEventStatus.FAILED
        ]
        assert len(failed_events) == 1
        updated_event = failed_events[0]
        assert updated_event is not None
        assert updated_event.status == OutboxEventStatus.FAILED
        assert updated_event.retry_count == 3
        assert "Max retries (3) exceeded" in updated_event.last_error

    def test_end_to_end_outbox_flow(self) -> None:
        """End-to-end test of outbox flow from payment to Kafka."""

        # Setup all repositories
        user_repo = InMemoryUserRepository()
        order_repo = InMemoryOrderRepository()
        payment_repo = InMemoryPaymentRepository()
        outbox_repo = InMemoryOutboxRepository()

        # Setup user and profile
        user = User(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            role=UserRole.ADVERTISER,
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            instagram_url=None,
            confirmed=False,
            topics=None,
            audience_gender=None,
            audience_age_min=None,
            audience_age_max=None,
            audience_geo=None,
            price=None,
            contact="test@example.com",
            profile_updated_at=None,
        )
        user_repo.save(user)

        # Setup order
        order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000002"),
            advertiser_id=user.user_id,
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
        order_repo.save(order)

        # Don't create payment upfront - let confirm_telegram_payment create it

        # Create services
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )
        payment_service = PaymentService(
            user_repo=user_repo,
            order_repo=order_repo,
            payment_repo=payment_repo,
            broadcaster=NoopOfferBroadcaster(),
            outbox_publisher=outbox_publisher,
        )

        # Create mock Kafka publisher
        kafka_publisher = MockKafkaPublisher()

        # 1. Confirm payment (creates outbox event)
        payment_service.confirm_telegram_payment(
            user_id=user.user_id,
            order_id=order.order_id,
            provider_payment_charge_id="test_charge_123",
            total_amount=100000,
            currency="RUB",
        )

        # 2. Process outbox events (activates order and publishes to Kafka)
        outbox_publisher.process_pending_events(kafka_publisher, max_retries=3)

        # Verify complete flow
        # Order should be activated after outbox processing
        updated_order = order_repo.get_by_id(order.order_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.ACTIVE

        # Outbox event should be published
        outbox_events = outbox_repo.get_pending_events()
        assert len(outbox_events) == 0  # No pending events left

        published_events = [
            e
            for e in outbox_repo.events.values()
            if e.status == OutboxEventStatus.PUBLISHED
        ]
        assert len(published_events) == 1

        # Kafka should have received the event
        assert len(kafka_publisher.published_events) == 1
        published_order = kafka_publisher.published_events[0]
        assert published_order.order_id == order.order_id
        assert published_order.status == OrderStatus.ACTIVE
