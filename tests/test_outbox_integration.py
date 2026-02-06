"""Integration tests for outbox functionality."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import AdvertiserProfile, Order, OutboxEvent, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
)


class MockKafkaPublisher:
    """Mock Kafka publisher for testing."""

    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.published_events = []

    async def publish(self, order):
        """Mock publish method."""
        if self.should_fail:
            raise Exception("Mock failure")
        self.published_events.append(order)
        return order  # Return the order as if it was processed


class TestOutboxIntegration:
    """Integration tests for outbox functionality."""

    @pytest.mark.asyncio
    async def test_payment_service_sets_pending_moderation(
        self, fake_tm: object
    ) -> None:
        """Payment service moves order to PENDING_MODERATION (no outbox)."""

        user_repo = InMemoryUserRepository()
        advertiser_repo = InMemoryAdvertiserProfileRepository()
        order_repo = InMemoryOrderRepository()
        payment_repo = InMemoryPaymentRepository()
        outbox_repo = InMemoryOutboxRepository()

        user = User(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(user)

        profile = AdvertiserProfile(
            user_id=user.user_id,
            phone="test@example.com",
            brand="Brand",
        )
        await advertiser_repo.save(profile)

        order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000002"),
            advertiser_id=user.user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        await order_repo.save(order)

        payment_service = PaymentService(
            user_repo=user_repo,
            advertiser_repo=advertiser_repo,
            order_repo=order_repo,
            payment_repo=payment_repo,
            transaction_manager=fake_tm,
        )

        result = await payment_service.confirm_telegram_payment(
            user_id=user.user_id,
            order_id=order.order_id,
            provider_payment_charge_id="test_charge_123",
            total_amount=100000,
            currency="RUB",
        )

        assert result is not None
        assert result.order_id == order.order_id

        updated_order = await order_repo.get_by_id(order.order_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.PENDING_MODERATION

        outbox_events = await outbox_repo.get_pending_events()
        assert len(outbox_events) == 0

    @pytest.mark.asyncio
    async def test_outbox_publisher_processes_event_successfully(self) -> None:
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
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,  # Start as NEW
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        await outbox_publisher.publish_order_activation(test_order)

        # Save the order in repository so it can be found during processing
        await order_repo.save(test_order)

        # Process events
        await outbox_publisher.process_pending_events(
            kafka_publisher, max_retries=3
        )

        # Get the processed event
        pending_events = await outbox_repo.get_pending_events()
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
        assert published_order.order_id == UUID(
            "00000000-0000-0000-0000-000000000001"
        )

    @pytest.mark.asyncio
    async def test_outbox_publisher_handles_processing_failure(self) -> None:
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
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        await outbox_publisher.publish_order_activation(test_order)

        # Save the order in repository so it can be found during processing
        await order_repo.save(test_order)

        # Process events (should fail and retry)
        await outbox_publisher.process_pending_events(
            kafka_publisher, max_retries=3
        )

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

    @pytest.mark.asyncio
    async def test_outbox_publisher_handles_max_retries_exceeded(self) -> None:
        """Outbox publisher marks event failed after max retries."""

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
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        await outbox_publisher.publish_order_activation(test_order)

        # Manually set retry count to max for the created event
        pending_events = await outbox_repo.get_pending_events()
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
        await outbox_repo.save(updated_event)

        # Save the order in repository so it can be found during processing
        await order_repo.save(test_order)

        # Process events (should mark as permanently failed)
        await outbox_publisher.process_pending_events(
            kafka_publisher, max_retries=3
        )

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

    @pytest.mark.asyncio
    async def test_end_to_end_outbox_flow(self, fake_tm: object) -> None:
        """End-to-end test of outbox flow from admin approval to Kafka."""

        user_repo = InMemoryUserRepository()
        advertiser_repo = InMemoryAdvertiserProfileRepository()
        order_repo = InMemoryOrderRepository()
        outbox_repo = InMemoryOutboxRepository()

        # Setup user and profile
        user = User(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        await user_repo.save(user)

        profile = AdvertiserProfile(
            user_id=user.user_id,
            phone="test@example.com",
            brand="Brand",
        )
        await advertiser_repo.save(profile)

        # Setup order
        order = Order(
            order_id=UUID("00000000-0000-0000-0000-000000000002"),
            advertiser_id=user.user_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Test offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        await order_repo.save(order)

        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )
        outbox_publisher.transaction_manager = fake_tm

        kafka_publisher = MockKafkaPublisher()

        # 1. Simulate admin approval: publish order activation to outbox
        activated_order = Order(
            order_id=order.order_id,
            advertiser_id=order.advertiser_id,
            order_type=order.order_type,
            product_link=order.product_link,
            offer_text=order.offer_text,
            ugc_requirements=order.ugc_requirements,
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
        async with fake_tm.transaction() as session:
            await order_repo.save(activated_order, session=session)
            await outbox_publisher.publish_order_activation(
                activated_order, session=session
            )

        # 2. Process outbox events (publishes to Kafka)
        await outbox_publisher.process_pending_events(
            kafka_publisher, max_retries=3
        )

        # Verify complete flow
        # Order should be activated after outbox processing
        updated_order = await order_repo.get_by_id(order.order_id)
        assert updated_order is not None
        assert updated_order.status == OrderStatus.ACTIVE

        # Outbox event should be published
        outbox_events = await outbox_repo.get_pending_events()
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
