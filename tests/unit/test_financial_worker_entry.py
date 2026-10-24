"""The outbox entrypoint runs configured financial work without Kafka."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from tests.postgres_financial.test_financial_outbox_routing import event
from ugc_bot.application.services.financial_event_router import (
    FinancialEventRouter,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryFinancialDeliveryRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
)


@pytest.mark.asyncio
async def test_actual_worker_entry_processes_financial_graph_without_kafka(
    monkeypatch,
):
    from ugc_bot import outbox_processor

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "test-token", "DATABASE_URL": "sqlite:///:memory:"}
    )
    repo = InMemoryOutboxRepository()
    financial = InMemoryFinancialDeliveryRepository(
        repo.events, repo._claimed_at
    )
    handled = asyncio.Event()
    value = event()
    await repo.save(value)
    legacy = event("order.activated")
    await repo.save(legacy)

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    class Handler:
        async def handle(self, received, *, session):
            assert received == value
            assert session is not None
            handled.set()

    child = OutboxPublisher(
        financial,
        InMemoryOrderRepository(),
        Transactions(),
        financial_router=FinancialEventRouter({value.event_type: Handler()}),
    )
    parent = OutboxPublisher(
        repo, InMemoryOrderRepository(), financial_delivery=child
    )

    class Container:
        disposed = False

        def build_outbox_deps(self):
            return parent, None

        async def dispose(self):
            self.disposed = True

    container = Container()
    real_sleep = asyncio.sleep

    async def controlled_sleep(delay):
        if delay == 1:
            await asyncio.wait_for(handled.wait(), timeout=1)
            raise KeyboardInterrupt()
        await real_sleep(3600)

    monkeypatch.setattr(outbox_processor, "load_config", lambda: config)
    monkeypatch.setattr(outbox_processor, "Container", lambda _: container)
    monkeypatch.setattr(
        outbox_processor, "configure_logging", lambda *a, **k: None
    )
    monkeypatch.setattr(outbox_processor, "log_startup_info", lambda **k: None)
    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    await outbox_processor.run_processor()
    assert (
        await repo.get_by_id(value.event_id)
    ).status == OutboxEventStatus.PUBLISHED
    assert await repo.get_by_id(legacy.event_id) == legacy
    assert container.disposed
