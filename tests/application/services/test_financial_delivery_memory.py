"""Memory parity confirmations of the PostgreSQL-driven negative contract."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.enums import OutboxEventStatus


@pytest.mark.asyncio
async def test_memory_negative_delivery_retry_identity_and_ownership():
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryFinancialDeliveryRepository,
    )

    owner = InMemoryFinancialDeliveryRepository()
    request, intent, legacy = (
        event(),
        event("financial.capture_intent"),
        event("order.activated"),
    )
    for row in [request, intent, legacy]:
        await owner.save(row)
    assert [e.event_id for e in await owner.get_pending_events()] == [
        request.event_id
    ]
    transport = AsyncMock()
    publisher = OutboxPublisher(
        owner, AsyncMock(), financial_router=FinancialEventRouter()
    )
    for retry in range(1, 4):
        await publisher.process_pending_events(transport)
        stored = await owner.get_by_id(request.event_id)
        assert stored.retry_count == retry
        assert stored.status == (
            OutboxEventStatus.FAILED
            if retry == 3
            else OutboxEventStatus.PENDING
        )
        assert stored.event_id == request.event_id
        assert stored.payload == request.payload
        assert stored.event_type == request.event_type
        assert "financial_handler_unready" in stored.last_error
    assert await owner.delete_processed_events(1, 1000) == 0
    for row in [request, intent, legacy]:
        await owner.save(replace(row, status=OutboxEventStatus.PROCESSING))
        owner._claimed_at[row.event_id] = row.created_at - timedelta(days=1)
    assert await owner.reset_stale_processing_events() == 1
    assert (
        await owner.get_by_id(request.event_id)
    ).status == OutboxEventStatus.PENDING
    assert (
        await owner.get_by_id(intent.event_id)
    ).status == OutboxEventStatus.PROCESSING
    assert (
        await owner.get_by_id(legacy.event_id)
    ).status == OutboxEventStatus.PROCESSING
    transport.publish.assert_not_awaited()
