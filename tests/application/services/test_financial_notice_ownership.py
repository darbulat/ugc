"""Monetary delivery never claims or recovers a notice-worker lease."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryFinancialDeliveryRepository,
)


@pytest.mark.asyncio
async def test_notice_requested_belongs_exclusively_to_notice_worker():
    repo = InMemoryFinancialDeliveryRepository()
    notice = event("financial.collaboration.notice_requested")
    await repo.save(notice)
    assert await repo.get_pending_events() == []
    assert await repo.claim_pending_events() == []
    processing = replace(notice, status=OutboxEventStatus.PROCESSING)
    await repo.save(processing)
    repo._claimed_at[notice.event_id] = notice.created_at - timedelta(days=1)
    assert await repo.reset_stale_processing_events() == 0
    assert await repo.get_by_id(notice.event_id) == processing
