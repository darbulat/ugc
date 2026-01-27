"""Tests for outbox repositories."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.infrastructure.memory_repositories import InMemoryOutboxRepository
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus


class TestInMemoryOutboxRepository:
    """Test in-memory outbox repository."""

    @pytest.mark.asyncio
    async def test_save_event(self) -> None:
        """Event is saved correctly."""

        repo = InMemoryOutboxRepository()

        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={"key": "value"},
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        await repo.save(event)

        # Verify event was saved
        assert len(repo.events) == 1
        saved_event = repo.events[event.event_id]
        assert saved_event.event_id == event.event_id
        assert saved_event.event_type == event.event_type
        assert saved_event.aggregate_id == event.aggregate_id
        assert saved_event.payload == event.payload
        assert saved_event.status == event.status

    @pytest.mark.asyncio
    async def test_get_pending_events(self) -> None:
        """Only pending events are returned."""

        repo = InMemoryOutboxRepository()

        # Create events with different statuses
        pending_event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PENDING,
            created_at=datetime(2023, 1, 1, 10, 0, tzinfo=timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        processing_event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000002"),
            event_type="order.activated",
            aggregate_id="order-124",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PROCESSING,
            created_at=datetime(2023, 1, 1, 10, 1, tzinfo=timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )

        published_event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000003"),
            event_type="order.activated",
            aggregate_id="order-125",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PUBLISHED,
            created_at=datetime(2023, 1, 1, 10, 2, tzinfo=timezone.utc),
            processed_at=datetime(2023, 1, 1, 10, 3, tzinfo=timezone.utc),
            retry_count=0,
            last_error=None,
        )

        await repo.save(pending_event)
        await repo.save(processing_event)
        await repo.save(published_event)

        # Get pending events
        pending_events = await repo.get_pending_events()

        # Verify only pending event is returned
        assert len(pending_events) == 1
        assert pending_events[0].event_id == pending_event.event_id

    @pytest.mark.asyncio
    async def test_get_pending_events_limit(self) -> None:
        """Limit is respected when getting pending events."""

        repo = InMemoryOutboxRepository()

        # Create multiple pending events
        for i in range(5):
            event = OutboxEvent(
                event_id=UUID(f"00000000-0000-0000-0000-000000000{i+1:03d}"),
                event_type="order.activated",
                aggregate_id=f"order-{i+1}",
                aggregate_type="order",
                payload={},
                status=OutboxEventStatus.PENDING,
                created_at=datetime(2023, 1, 1, 10, i, tzinfo=timezone.utc),
                processed_at=None,
                retry_count=0,
                last_error=None,
            )
            await repo.save(event)

        # Get with limit
        pending_events = await repo.get_pending_events(limit=3)

        # Verify limit is respected
        assert len(pending_events) == 3

    @pytest.mark.asyncio
    async def test_get_pending_events_ordered_by_created_at(self) -> None:
        """Events are ordered by creation time (oldest first)."""

        repo = InMemoryOutboxRepository()

        # Create events in reverse chronological order
        for i in [3, 1, 2]:
            event = OutboxEvent(
                event_id=UUID(f"00000000-0000-0000-0000-000000000{i+1:03d}"),
                event_type="order.activated",
                aggregate_id=f"order-{i+1}",
                aggregate_type="order",
                payload={},
                status=OutboxEventStatus.PENDING,
                created_at=datetime(2023, 1, 1, 10, i, tzinfo=timezone.utc),
                processed_at=None,
                retry_count=0,
                last_error=None,
            )
            await repo.save(event)

        # Get pending events
        pending_events = await repo.get_pending_events()

        # Verify order (oldest first)
        assert len(pending_events) == 3
        assert pending_events[0].aggregate_id == "order-2"  # created_at 10:1
        assert pending_events[1].aggregate_id == "order-3"  # created_at 10:2
        assert pending_events[2].aggregate_id == "order-4"  # created_at 10:3

    @pytest.mark.asyncio
    async def test_mark_as_processing(self) -> None:
        """Event status is updated to processing."""

        repo = InMemoryOutboxRepository()

        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )
        await repo.save(event)

        # Mark as processing
        await repo.mark_as_processing(event.event_id)

        # Verify status was updated
        updated_event = repo.events[event.event_id]
        assert updated_event.status == OutboxEventStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_mark_as_published(self) -> None:
        """Event is marked as published with processed_at timestamp."""

        repo = InMemoryOutboxRepository()

        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )
        await repo.save(event)

        processed_at = datetime.now(timezone.utc)

        # Mark as published
        await repo.mark_as_published(event.event_id, processed_at)

        # Verify event was updated
        updated_event = repo.events[event.event_id]
        assert updated_event.status == OutboxEventStatus.PUBLISHED
        assert updated_event.processed_at == processed_at

    @pytest.mark.asyncio
    async def test_mark_as_failed(self) -> None:
        """Event is marked as failed with error and retry count."""

        repo = InMemoryOutboxRepository()

        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PROCESSING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=1,
            last_error=None,
        )
        await repo.save(event)

        error_msg = "Kafka connection failed"
        new_retry_count = 2

        # Mark as failed
        await repo.mark_as_failed(event.event_id, error_msg, new_retry_count)

        # Verify event was updated
        updated_event = repo.events[event.event_id]
        assert updated_event.status == OutboxEventStatus.FAILED
        assert updated_event.last_error == error_msg
        assert updated_event.retry_count == new_retry_count

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self) -> None:
        """Existing event is returned by ID."""

        repo = InMemoryOutboxRepository()

        event = OutboxEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
            event_type="order.activated",
            aggregate_id="order-123",
            aggregate_type="order",
            payload={},
            status=OutboxEventStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            processed_at=None,
            retry_count=0,
            last_error=None,
        )
        await repo.save(event)

        # Get by ID
        retrieved_event = await repo.get_by_id(event.event_id)

        # Verify correct event was returned
        assert retrieved_event is not None
        assert retrieved_event.event_id == event.event_id
        assert retrieved_event.event_type == event.event_type

    @pytest.mark.asyncio
    async def test_get_by_id_nonexistent(self) -> None:
        """None is returned for nonexistent event ID."""

        repo = InMemoryOutboxRepository()

        # Get by non-existent ID
        retrieved_event = await repo.get_by_id(
            UUID("00000000-0000-0000-0000-000000000999")
        )

        # Verify None was returned
        assert retrieved_event is None

    @pytest.mark.asyncio
    async def test_mark_as_processing_nonexistent_event(self) -> None:
        """No error when marking nonexistent event as processing."""

        repo = InMemoryOutboxRepository()

        # This should not raise an exception
        await repo.mark_as_processing(UUID("00000000-0000-0000-0000-000000000999"))

    @pytest.mark.asyncio
    async def test_mark_as_published_nonexistent_event(self) -> None:
        """No error when marking nonexistent event as published."""

        repo = InMemoryOutboxRepository()

        processed_at = datetime.now(timezone.utc)

        # This should not raise an exception
        await repo.mark_as_published(
            UUID("00000000-0000-0000-0000-000000000999"), processed_at
        )

    @pytest.mark.asyncio
    async def test_mark_as_failed_nonexistent_event(self) -> None:
        """No error when marking nonexistent event as failed."""

        repo = InMemoryOutboxRepository()

        # This should not raise an exception
        await repo.mark_as_failed(
            UUID("00000000-0000-0000-0000-000000000999"), "error", 1
        )
