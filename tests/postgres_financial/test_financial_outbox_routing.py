"""Processor ownership boundaries exercised on migrated PostgreSQL."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


def event(
    event_type="financial.v1.snapshot_requested",
    *,
    status=OutboxEventStatus.PENDING,
):
    now = datetime.now(timezone.utc) - timedelta(days=30)
    return OutboxEvent(
        event_id=uuid4(),
        event_type=event_type,
        aggregate_id=str(uuid4()),
        aggregate_type="order",
        payload={},
        status=status,
        created_at=now,
        processed_at=now if status == OutboxEventStatus.PUBLISHED else None,
        retry_count=0,
        last_error=None,
    )


@pytest_asyncio.fixture
async def routing_env(financial_pg_engine):
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=1, max_overflow=0
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SqlAlchemyOutboxRepository(factory), factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_financial_event_never_activates_order(routing_env):
    repo, factory = routing_env
    financial = event()
    orders, legacy_publisher = AsyncMock(), AsyncMock()
    processor = OutboxPublisher(
        repo, orders, SessionTransactionManager(factory)
    )
    await repo.save(financial)
    await processor.process_pending_events(legacy_publisher)
    stored = await repo.get_by_id(financial.event_id)
    assert stored is not None
    assert stored.status == OutboxEventStatus.PENDING
    assert stored.retry_count == 0, (
        "Legacy processor must not claim financial events"
    )
    assert stored.last_error is None
    orders.save.assert_not_awaited()
    legacy_publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_retention_preserves_financial_identity(routing_env):
    repo, _ = routing_env
    financial = event(status=OutboxEventStatus.PUBLISHED)
    await repo.save(financial)
    await repo.delete_processed_events(retention_days=1, batch_size=100)
    stored = await repo.get_by_id(financial.event_id)
    assert stored is not None, (
        "Legacy retention must not erase financial replay identity"
    )
    assert stored.status == OutboxEventStatus.PUBLISHED


@pytest.mark.asyncio
async def test_legacy_stale_reset_cannot_reclaim_financial_lease(routing_env):
    repo, factory = routing_env
    financial = event(status=OutboxEventStatus.PROCESSING)
    await repo.save(financial)
    async with factory.begin() as session:
        await session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.event_id == financial.event_id)
            .values(claimed_at=financial.created_at)
        )
    await repo.reset_stale_processing_events(stale_after_minutes=15)
    stored = await repo.get_by_id(financial.event_id)
    assert stored is not None
    assert stored.status == OutboxEventStatus.PROCESSING
