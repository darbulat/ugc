"""Financial handlers are awaited inside the publisher's transaction."""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryFinancialDeliveryRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
)
from ugc_bot.outbox_processor import OutboxProcessor


@dataclass
class Handler:
    expected_session: object
    fail: bool = False
    called: int = 0

    async def handle(self, value, *, session):
        assert session is self.expected_session
        self.called += 1
        if self.fail:
            raise RuntimeError("handler rejected source fact")


class TransactionManager:
    def __init__(self):
        self.session = object()
        self.committed = 0
        self.rolled_back = 0

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self.session
        except Exception:
            self.rolled_back += 1
            raise
        else:
            self.committed += 1


@pytest.mark.asyncio
async def test_registered_financial_handler_publishes_without_kafka():
    tm = TransactionManager()
    handler = Handler(tm.session)
    owner = InMemoryFinancialDeliveryRepository()
    value = event()
    await owner.save(value)
    router = FinancialEventRouter({value.event_type: handler})
    publisher = OutboxPublisher(
        owner, InMemoryOrderRepository(), tm, financial_router=router
    )
    await OutboxProcessor(publisher, None).process_once()
    stored = await owner.get_by_id(value.event_id)
    assert handler.called == 1
    assert stored.status == OutboxEventStatus.PUBLISHED
    assert stored.retry_count == 0
    assert stored.last_error is None
    assert tm.rolled_back == 0
    await OutboxProcessor(publisher, None).process_once()
    assert handler.called == 1


@pytest.mark.asyncio
async def test_failed_handler_rolls_back_then_records_retry():
    tm = TransactionManager()
    handler = Handler(tm.session, fail=True)
    owner = InMemoryFinancialDeliveryRepository()
    value = event()
    await owner.save(value)
    publisher = OutboxPublisher(
        owner,
        InMemoryOrderRepository(),
        tm,
        financial_router=FinancialEventRouter({value.event_type: handler}),
    )
    await publisher.process_pending_events(None)
    stored = await owner.get_by_id(value.event_id)
    assert handler.called == 1
    assert tm.rolled_back == 1
    assert stored.status == OutboxEventStatus.PENDING
    assert stored.retry_count == 1
    assert "handler rejected source fact" in stored.last_error


@pytest.mark.asyncio
async def test_financial_only_worker_leaves_legacy_activation_unclaimed():
    tm = TransactionManager()
    repo = InMemoryOutboxRepository()
    owner = InMemoryFinancialDeliveryRepository(repo.events, repo._claimed_at)
    financial, legacy = event(), event("order.activated")
    for value in (financial, legacy):
        await repo.save(value)
    handler = Handler(tm.session)
    child = OutboxPublisher(
        owner,
        InMemoryOrderRepository(),
        tm,
        financial_router=FinancialEventRouter({financial.event_type: handler}),
    )
    parent = OutboxPublisher(
        repo, InMemoryOrderRepository(), tm, financial_delivery=child
    )
    await OutboxProcessor(parent, None).process_once()
    assert (
        await repo.get_by_id(financial.event_id)
    ).status == OutboxEventStatus.PUBLISHED
    assert await repo.get_by_id(legacy.event_id) == legacy
    assert legacy.event_id not in repo._claimed_at


@pytest.mark.asyncio
async def test_real_handler_requires_caller_transaction():
    handler = Handler(object())
    value = event()
    router = FinancialEventRouter({value.event_type: handler})
    with pytest.raises(ValueError, match="financial_transaction_required"):
        await router.route(value, session=None)
    assert handler.called == 0
