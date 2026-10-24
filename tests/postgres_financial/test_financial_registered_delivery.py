"""A financial consumer and delivery marker share a real SQL transaction."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyFinancialDeliveryRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.mark.asyncio
@pytest.mark.parametrize("reject", [False, True])
async def test_handler_write_and_delivery_marker_commit_or_rollback_together(
    financial_pg_engine,
    reject,
):
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = SqlAlchemyFinancialDeliveryRepository(factory)
    source, consequence = event(), event("financial.test.consequence")

    class Handler:
        async def handle(self, value, *, session):
            assert value.event_id == source.event_id
            await owner.save(consequence, session=session)
            if reject:
                raise ValueError("source_fact_rejected")

    publisher = OutboxPublisher(
        owner,
        SqlAlchemyOrderRepository(factory),
        SessionTransactionManager(factory),
        financial_router=FinancialEventRouter({source.event_type: Handler()}),
    )
    try:
        await owner.save(source)
        if reject:
            with pytest.raises(ValueError, match="source_fact_rejected"):
                await publisher._process_one_event(source, None, 3)
        else:
            await publisher._process_one_event(source, None, 3)
        stored = await owner.get_by_id(source.event_id)
        effect = await owner.get_by_id(consequence.event_id)
        if reject:
            assert stored.status == OutboxEventStatus.PENDING
            assert stored.processed_at is None
            assert effect is None
        else:
            assert stored.status == OutboxEventStatus.PUBLISHED
            assert stored.processed_at is not None
            assert effect == consequence
    finally:
        await engine.dispose()
