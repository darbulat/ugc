"""A bounded test wait preserves actual target-consumer failures."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.financial_worker import process_until_published
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyFinancialDeliveryRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.outbox_processor import OutboxProcessor


def source(engine, *, kind="financial.fixture_wait", status="pending"):
    identity = uuid4()
    with Session(engine) as db, db.begin():
        db.add(
            OutboxEventModel(
                event_id=identity,
                event_type=kind,
                aggregate_id=str(uuid4()),
                aggregate_type="synthetic_wait",
                payload={},
                status=status,
                created_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
                retry_count=0,
            )
        )
    return identity


@pytest.mark.asyncio
async def test_wait_preserves_actual_consumer_error(financial_pg_engine):
    identity = source(financial_pg_engine)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    publisher = OutboxPublisher(
        SqlAlchemyFinancialDeliveryRepository(factory),
        SqlAlchemyOrderRepository(factory),
        SessionTransactionManager(factory),
        financial_router=FinancialEventRouter(),
    )
    worker = OutboxProcessor(publisher, None)
    try:
        with pytest.raises(
            AssertionError, match="financial_worker_target_error"
        ):
            await process_until_published(
                worker, financial_pg_engine, (identity,)
            )
        with Session(financial_pg_engine) as db:
            row = db.get(OutboxEventModel, identity)
            assert row.status == OutboxEventStatus.PENDING
            assert row.retry_count == 1
            assert "financial_handler_unready" in row.last_error
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        None,
        "financial.capture_intent",
        "financial.collaboration.notice_requested",
    ],
)
async def test_wait_rejects_missing_or_separately_owned_target(
    financial_pg_engine, kind
):
    identity = (
        uuid4() if kind is None else source(financial_pg_engine, kind=kind)
    )
    worker = SimpleNamespace(max_retries=3, process_once=AsyncMock())
    with pytest.raises(
        AssertionError, match="financial_worker_target_missing_or_unowned"
    ):
        await process_until_published(worker, financial_pg_engine, (identity,))
    worker.process_once.assert_not_awaited()


@pytest.mark.asyncio
async def test_wait_fails_when_worker_makes_no_progress(financial_pg_engine):
    identity = source(financial_pg_engine)
    worker = SimpleNamespace(max_retries=3, process_once=AsyncMock())
    with pytest.raises(AssertionError, match="financial_worker_no_progress"):
        await process_until_published(worker, financial_pg_engine, (identity,))
    worker.process_once.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["published", "failed"])
async def test_wait_respects_already_terminal_target(
    financial_pg_engine, status
):
    identity = source(financial_pg_engine, status=status)
    worker = SimpleNamespace(max_retries=3, process_once=AsyncMock())
    if status == "failed":
        with pytest.raises(
            AssertionError, match="financial_worker_target_failed"
        ):
            await process_until_published(
                worker, financial_pg_engine, (identity,)
            )
    else:
        await process_until_published(worker, financial_pg_engine, (identity,))
    worker.process_once.assert_not_awaited()
