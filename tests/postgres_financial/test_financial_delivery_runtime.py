"""Real capture -> production factories -> negative delivery."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.conftest import (
    financial_pg_engine as _shared_engine,
)
from tests.postgres_financial.test_v1_capture import (
    capture_env as _capture_env,
)
from tests.postgres_financial.test_v1_capture import (
    telegram_receipt,
)
from ugc_bot.config import AppConfig
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import build_outbox_deps
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus
from ugc_bot.infrastructure.db.ledger_schema import NAMES as LEDGER_TABLE_NAMES
from ugc_bot.infrastructure.db.models import (
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.outbox_processor import OutboxProcessor

capture_env = _capture_env


@pytest.fixture
def financial_pg_engine(request):
    # A bounded processor batch must see only this scenario's actual queue,
    # independently of whether an earlier test happened to process it.
    yield from _shared_engine.__wrapped__(request)


def durable_state(env):
    """All columns, including financial obligations/journal/projections."""
    tables = [
        OrderModel.__table__,
        PaymentModel.__table__,
        OrderItemModel.__table__,
        PaymentItemAllocationModel.__table__,
    ]
    tables += [
        t
        for t in OrderModel.metadata.sorted_tables
        if (
            t.name in (*LEDGER_TABLE_NAMES, "item_assignments")
            or any(
                s in t.name
                for s in ("financial", "obligation", "journal", "ledger")
            )
        )
        and t not in tables
    ]
    with Session(env["pg"]) as db:
        state = {
            t.name: sorted(
                (repr(dict(r)) for r in db.execute(select(t)).mappings())
            )
            for t in tables
        }
        assert set(LEDGER_TABLE_NAMES) | {"item_assignments"} <= state.keys()
        events = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"])
            )
        ).all()
        intent = next(
            e for e in events if e.event_type == "financial.capture_intent"
        )
        request = next(
            e
            for e in events
            if e.event_type == "financial.client_snapshot_requested"
        )
        return (
            state,
            {
                c.name: deepcopy(getattr(intent, c.name))
                for c in intent.__table__.columns
            },
            (request.event_id, request.event_type, deepcopy(request.payload)),
        )


async def captured_runtime(env):
    receipt = telegram_receipt(env)
    payment = await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    config = AppConfig()
    config.kafka.kafka_enabled = False
    repos = build_repos(env["factory"])
    publisher, kafka = build_outbox_deps(
        config, repos, SessionTransactionManager(env["factory"])
    )
    assert kafka is None
    legacy = AsyncMock()
    return OutboxProcessor(publisher, legacy), legacy, payment, receipt, repos


@pytest.mark.asyncio
async def test_unready_capture_request_records_retry_without_money_changes(
    capture_env,
):
    env = capture_env
    processor, legacy, payment, _, _ = await captured_runtime(env)
    with Session(env["pg"]) as db:
        assert db.get(PaymentModel, payment.payment_id).captured_minor == 220000
        assert (
            len(
                db.scalars(
                    select(OrderItemModel).where(
                        OrderItemModel.order_id == env["order"]
                    )
                ).all()
            )
            == 2
        )
        assert (
            len(
                db.scalars(
                    select(PaymentItemAllocationModel).where(
                        PaymentItemAllocationModel.payment_id
                        == payment.payment_id
                    )
                ).all()
            )
            == 3
        )
        assert (
            db.get(OrderModel, env["order"]).status
            == OrderStatus.PENDING_MODERATION
        )
    before = durable_state(env)
    await processor.process_once()
    assert durable_state(env) == before
    legacy.publish.assert_not_awaited()
    with Session(env["pg"]) as db:
        request = db.get(OutboxEventModel, before[2][0])
        assert request.retry_count == 1
        assert request.status == OutboxEventStatus.PENDING
        assert "financial_handler_unready" in request.last_error


@pytest.mark.asyncio
async def test_financial_owner_recovers_only_its_stale_delivery(capture_env):
    from datetime import timedelta

    from tests.postgres_financial.test_financial_outbox_routing import event

    env = capture_env
    processor, legacy, _, _, repos = await captured_runtime(env)
    before = durable_state(env)
    future = event("financial.future.unknown")
    stale_legacy = event("order.activated", status=OutboxEventStatus.PROCESSING)
    await repos["outbox_repo"].save(future)
    await repos["outbox_repo"].save(stale_legacy)
    with Session(env["pg"]) as db, db.begin():
        for identity in [before[2][0], stale_legacy.event_id]:
            row = db.get(OutboxEventModel, identity)
            row.status = OutboxEventStatus.PROCESSING
            row.claimed_at = env["now"] - timedelta(days=1)
    owner = repos["financial_delivery_repo"]
    assert await owner.reset_stale_processing_events() == 1
    with Session(env["pg"]) as db:
        assert (
            db.get(OutboxEventModel, before[2][0]).status
            == OutboxEventStatus.PENDING
        )
        assert (
            db.get(OutboxEventModel, stale_legacy.event_id).status
            == OutboxEventStatus.PROCESSING
        )
    await processor.outbox_publisher.financial_delivery.process_pending_events(
        legacy
    )
    stored = await owner.get_by_id(future.event_id)
    assert stored.retry_count == 1
    assert "financial.future.unknown" in stored.last_error
    assert durable_state(env) == before
    legacy.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_receipt_survives_financial_cleanup_and_capture_replay(
    capture_env,
):
    from tests.postgres_financial.test_financial_outbox_routing import event

    env = capture_env
    processor, legacy, payment, receipt, repos = await captured_runtime(env)
    before = durable_state(env)
    for _ in range(4):
        await processor.process_once()
    with Session(env["pg"]) as db:
        request = db.get(OutboxEventModel, before[2][0])
        assert request.status == OutboxEventStatus.FAILED
        assert request.retry_count == 3
        assert "financial_handler_unready" in request.last_error
    old_legacy = event("order.activated", status=OutboxEventStatus.FAILED)
    await repos["outbox_repo"].save(old_legacy)
    owner = repos["financial_delivery_repo"]
    assert await owner.delete_processed_events(1, 1000) == 0
    assert (
        await repos["outbox_repo"].get_by_id(old_legacy.event_id) == old_legacy
    )
    replay = await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    assert replay.payment_id == payment.payment_id
    assert durable_state(env) == before
    legacy.publish.assert_not_awaited()
