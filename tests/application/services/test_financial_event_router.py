"""The in-memory outbox obeys the same processor ownership contract."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryOutboxRepository


@pytest.fixture
def financial_event():
    return OutboxEvent(
        event_id=uuid4(),
        event_type="financial.v1.snapshot_requested",
        aggregate_id=str(uuid4()),
        aggregate_type="order",
        payload={},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        processed_at=None,
        retry_count=0,
        last_error=None,
    )


@pytest.mark.asyncio
async def test_memory_legacy_claim_excludes_financial_namespace(
    financial_event,
):
    repo = InMemoryOutboxRepository()
    event = financial_event
    await repo.save(event)
    assert await repo.get_pending_events() == []
    assert await repo.claim_pending_events() == []
    assert await repo.get_by_id(event.event_id) == event


@pytest.mark.asyncio
async def test_memory_retention_preserves_financial_identity(financial_event):
    repo = InMemoryOutboxRepository()
    old = datetime.now(timezone.utc) - timedelta(days=30)
    event = replace(
        financial_event,
        status=OutboxEventStatus.PUBLISHED,
        created_at=old,
        processed_at=old,
    )
    await repo.save(event)
    await repo.delete_processed_events(1, 100)
    assert await repo.get_by_id(event.event_id) == event


@pytest.mark.asyncio
async def test_memory_stale_reset_preserves_financial_lease(financial_event):
    repo = InMemoryOutboxRepository()
    event = replace(financial_event, status=OutboxEventStatus.PROCESSING)
    await repo.save(event)
    repo._claimed_at[event.event_id] = datetime.now(timezone.utc) - timedelta(
        days=1
    )
    assert await repo.reset_stale_processing_events() == 0
    assert await repo.get_by_id(event.event_id) == event
