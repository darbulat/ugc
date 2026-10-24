"""Separate notice leases remain untouched by ordinary financial delivery."""

import os
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyFinancialDeliveryRepository,
)


@pytest.mark.asyncio
async def test_general_financial_owner_never_recovers_or_claims_notice_lease():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("FINANCIAL_TEST_DATABASE_URL is required")
    # A private schema keeps this destructive ownership probe self-contained.
    with isolated_financial_database(url) as pg:
        engine = create_async_engine(pg.url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repo = SqlAlchemyFinancialDeliveryRepository(factory)
        notice = event("financial.collaboration.notice_requested")
        try:
            await repo.save(notice)
            assert await repo.get_pending_events() == []
            assert await repo.claim_pending_events() == []
            async with factory.begin() as db:
                await db.execute(
                    update(OutboxEventModel)
                    .where(OutboxEventModel.event_id == notice.event_id)
                    .values(
                        status=OutboxEventStatus.PROCESSING,
                        claimed_at=notice.created_at - timedelta(days=1),
                    )
                )
            assert await repo.reset_stale_processing_events() == 0
            assert (
                await repo.get_by_id(notice.event_id)
            ).status == OutboxEventStatus.PROCESSING
            assert await repo.delete_processed_events(1, 100) == 0
        finally:
            await engine.dispose()
