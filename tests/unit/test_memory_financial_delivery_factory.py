"""Memory delivery ownership through the existing production factory seam."""

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.container.service_factory import build_outbox_deps
from ugc_bot.domain.entities import Order, OutboxEvent
from ugc_bot.domain.enums import OrderStatus, OrderType, OutboxEventStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
)
from ugc_bot.outbox_processor import OutboxProcessor


def event(kind, order_id, **changes):
    return replace(
        OutboxEvent(
            uuid4(),
            kind,
            str(order_id),
            "order",
            {"order_id": str(order_id), "identity": str(uuid4())},
            OutboxEventStatus.PENDING,
            datetime.now(timezone.utc),
            None,
            0,
            None,
        ),
        **changes,
    )


@pytest.mark.asyncio
async def test_financial_retention_never_deletes_either_owners_history():
    repo, _, publisher = dependencies()
    owner = publisher.financial_delivery.outbox_repo
    old = datetime.now(timezone.utc) - timedelta(days=40)
    records = [
        event(kind, uuid4(), status=status, created_at=old, processed_at=old)
        for kind in (
            "financial.snapshot_requested",
            "financial.future.v9",
            "financial.capture_intent",
            "order.activated",
        )
        for status in (OutboxEventStatus.PUBLISHED, OutboxEventStatus.FAILED)
    ]
    for record in records:
        await repo.save(record)
    assert await owner.delete_processed_events(1, 100) == 0
    assert repo.events == {record.event_id: record for record in records}
    assert await repo.delete_processed_events(1, 100) == 2
    for record in records:
        if record.event_type.startswith("financial."):
            assert await repo.get_by_id(record.event_id) == record


@pytest.mark.asyncio
async def test_stale_recovery_respects_owner_and_shares_live_lease_store():
    repo, _, publisher = dependencies()
    owner = publisher.financial_delivery.outbox_repo
    request = event("financial.future.v9", uuid4())
    legacy = event("order.activated", uuid4())
    control = event(
        "financial.capture_intent", uuid4(), status=OutboxEventStatus.PROCESSING
    )
    for record in (request, legacy, control):
        await repo.save(record)
    assert await owner.get_pending_events() == [request]
    assert await repo.get_pending_events() == [legacy]
    await owner.claim_pending_events()
    await repo.claim_pending_events()
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    for record in (request, legacy, control):
        repo._claimed_at[record.event_id] = old
    assert owner.events is repo.events
    assert owner._claimed_at is repo._claimed_at
    assert await owner.reset_stale_processing_events() == 1
    assert (
        await repo.get_by_id(request.event_id)
    ).status == OutboxEventStatus.PENDING
    assert (
        await repo.get_by_id(legacy.event_id)
    ).status == OutboxEventStatus.PROCESSING
    assert await repo.get_by_id(control.event_id) == control
    assert control.event_id in repo._claimed_at
    assert request.event_id not in repo._claimed_at
    assert await repo.reset_stale_processing_events() == 1
    assert (
        await repo.get_by_id(legacy.event_id)
    ).status == OutboxEventStatus.PENDING
    assert await repo.get_by_id(control.event_id) == control


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "financial.snapshot_requested",
        "financial.future.v9",
        "financial.capture_intent.future",
    ],
)
async def test_unknown_delivery_exhausts_retries_preserving_identity(kind):
    repo, _, publisher = dependencies()
    request = event(kind, uuid4())
    control = event("financial.capture_intent", uuid4())
    await repo.save(request)
    await repo.save(control)
    transport = AsyncMock()
    processor = OutboxProcessor(publisher, transport, max_retries=2)
    for retry in (1, 2):
        await processor.process_once()
        saved = await repo.get_by_id(request.event_id)
        assert saved == replace(
            request,
            retry_count=retry,
            last_error=f"financial_handler_unready: {kind}",
            status=OutboxEventStatus.FAILED
            if retry == 2
            else OutboxEventStatus.PENDING,
        )
    terminal = await repo.get_by_id(request.event_id)
    await processor.process_once()
    assert await repo.get_by_id(request.event_id) == terminal
    assert await repo.get_by_id(control.event_id) == control
    assert (
        await publisher.financial_delivery.cleanup_processed_events(1, 100) == 0
    )
    assert await repo.get_by_id(request.event_id) == terminal
    transport.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_legacy_constructors_remain_legacy_only():
    from ugc_bot.application.services.outbox_publisher import OutboxPublisher

    repo = InMemoryOutboxRepository()
    orders = InMemoryOrderRepository()
    request = event("financial.future.v9", uuid4())
    await repo.save(request)
    for publisher in (
        OutboxPublisher(repo, orders),
        OutboxPublisher(repo, orders, None),
    ):
        assert publisher.financial_delivery is None
        await OutboxProcessor(publisher, AsyncMock()).process_once()
        assert await repo.get_by_id(request.event_id) == request


def dependencies():
    repo = InMemoryOutboxRepository()
    orders = InMemoryOrderRepository()
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "KAFKA_ENABLED": False,
        }
    )
    publisher, transport = build_outbox_deps(
        config,
        {"outbox_repo": repo, "order_repo": orders},
        None,
    )
    assert transport is None
    return repo, orders, publisher


@pytest.mark.asyncio
async def test_factory_processor_retries_unready_without_control_mutation():
    repo, orders, publisher = dependencies()
    order = Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_ONLY,
        "link",
        "offer",
        None,
        10.0,
        1,
        OrderStatus.NEW,
        datetime.now(timezone.utc),
    )
    await orders.save(order)
    request = event("financial.snapshot_requested", order.order_id)
    control = event("financial.capture_intent", order.order_id)
    await repo.save(request)
    await repo.save(control)
    before_control = asdict(control)
    before_order = asdict(order)
    transport = AsyncMock()
    await OutboxProcessor(publisher, transport).process_once()
    saved = await repo.get_by_id(request.event_id)
    assert saved.retry_count == 1
    assert (
        saved.last_error
        == "financial_handler_unready: financial.snapshot_requested"
    )
    assert saved.status == OutboxEventStatus.PENDING
    assert (saved.event_id, saved.event_type, saved.payload) == (
        request.event_id,
        request.event_type,
        request.payload,
    )
    assert asdict(await repo.get_by_id(control.event_id)) == before_control
    assert asdict(await orders.get_by_id(order.order_id)) == before_order
    transport.publish.assert_not_awaited()
