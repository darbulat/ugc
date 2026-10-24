"""Real-PG confirmations; no OS crash or ready-consumer claim."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial.conftest import (
    financial_pg_engine as _shared_engine,
)
from tests.postgres_financial.test_financial_delivery_runtime import (
    capture_env as _capture_env,
)
from tests.postgres_financial.test_financial_delivery_runtime import (
    durable_state,
)
from tests.postgres_financial.test_v1_capture import telegram_receipt
from ugc_bot.config import AppConfig
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import build_outbox_deps
from ugc_bot.domain.enums import OrderStatus, OutboxEventStatus
from ugc_bot.infrastructure.db.models import OrderModel, OutboxEventModel
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.outbox_processor import OutboxProcessor

capture_env = _capture_env


@pytest.fixture
def financial_pg_engine(request):
    # Global queue discovery needs a fresh schema: one process_once handles
    # only a bounded batch, not all earlier scenarios' retained requests.
    yield from _shared_engine.__wrapped__(request)


class ActivationProbe:
    """Observe legacy activation without replacing financial paths."""

    def __init__(self):
        self.orders = []

    async def publish(self, order):
        self.orders.append(order)


async def runtime(env):
    receipt = telegram_receipt(env)
    await env["service"].confirm_telegram_payment(
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
    probe = ActivationProbe()
    return OutboxProcessor(publisher, probe), probe, repos


def request_state(env, identity):
    with Session(env["pg"]) as db:
        row = db.get(OutboxEventModel, identity)
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def assert_negative_delivery(env, before, probe):
    assert durable_state(env) == before
    row = request_state(env, before[2][0])
    assert row["status"] == OutboxEventStatus.PENDING
    assert row["retry_count"] == 1
    assert "financial_handler_unready" in row["last_error"]
    assert row["processed_at"] is None
    assert row["claimed_at"] is not None
    assert probe.orders == []
    with Session(env["pg"]) as db:
        assert (
            db.get(OrderModel, env["order"]).status
            == OrderStatus.PENDING_MODERATION
        )
        assert not db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type == "order.activated",
            )
        ).all()


@pytest.mark.asyncio
async def test_independent_financial_claim_skips_live_uncommitted_claim(
    capture_env, record_property
):
    env = capture_env
    processor, probe, repos = await runtime(env)
    before = durable_state(env)
    original = request_state(env, before[2][0])
    # Reuse the already-owned scoped URL, including its search_path; do not
    # revalidate this routed URL as though it were an unscoped database URL.
    engine_b = create_async_engine(env["pg"].url, pool_size=1, max_overflow=0)
    factory_b = async_sessionmaker(engine_b, expire_on_commit=False)
    owner_a = repos["financial_delivery_repo"]
    owner_b = build_repos(factory_b)["financial_delivery_repo"]
    try:
        async with env["factory"]() as a, a.begin():
            pid_a = await a.scalar(text("select pg_backend_pid()"))
            expected = set(
                await a.scalars(
                    select(OutboxEventModel.event_id).where(
                        OutboxEventModel.status == OutboxEventStatus.PENDING,
                        OutboxEventModel.event_type.like("financial.%"),
                        OutboxEventModel.event_type.not_in(
                            (
                                "financial.capture_intent",
                                "financial.collaboration.notice_requested",
                            )
                        ),
                    )
                )
            )
            claimed_a = await owner_a.claim_pending_events(1000, session=a)
            assert {e.event_id for e in claimed_a} == expected
            assert before[2][0] in expected
            await a.flush()
            held = await a.get(OutboxEventModel, before[2][0])
            assert held.status == OutboxEventStatus.PROCESSING
            assert held.claimed_at is not None
            assert held.retry_count == 0
            # Explicit connection rendezvous: B executes only after A claimed
            # and flushed, and completes while A still owns its transaction.
            async with factory_b.begin() as b:
                pid_b = await b.scalar(text("select pg_backend_pid()"))
                assert pid_a != pid_b
                record_property("claim_backend_pids", f"{pid_a},{pid_b}")
                await b.execute(text("set local statement_timeout = '5s'"))
                claimed_b = await owner_b.claim_pending_events(1000, session=b)
                assert claimed_b == []
                assert {e.event_id for e in claimed_a}.isdisjoint(
                    e.event_id for e in claimed_b
                )
                visible = await b.get(OutboxEventModel, before[2][0])
                assert visible.status == OutboxEventStatus.PENDING
                assert visible.retry_count == 0
                assert visible.claimed_at is None
            assert a.in_transaction()
            assert durable_state(env) == before
            await a.rollback()
        assert request_state(env, before[2][0]) == original
        await processor.process_once()
        assert_negative_delivery(env, before, probe)
    finally:
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_committed_abandoned_claim_recovers_through_negative_processor(
    capture_env, record_property
):
    env = capture_env
    processor, probe, repos = await runtime(env)
    before = durable_state(env)
    original = request_state(env, before[2][0])
    engine_a = create_async_engine(env["pg"].url, pool_size=1, max_overflow=0)
    factory_a = async_sessionmaker(engine_a, expire_on_commit=False)
    owner = build_repos(factory_a)["financial_delivery_repo"]
    try:
        async with factory_a.begin() as a:
            pid_a = await a.scalar(text("select pg_backend_pid()"))
            claimed = await owner.claim_pending_events(1000, session=a)
            assert before[2][0] in {event.event_id for event in claimed}
            assert all(
                event.event_type != "financial.capture_intent"
                for event in claimed
            )
        # The claimant commits and closes without handling the event. This is
        # an abandoned committed lease, NOT an actual OS/process crash.
        committed = request_state(env, before[2][0])
        assert committed["status"] == OutboxEventStatus.PROCESSING
        assert committed["claimed_at"] is not None
        assert committed["retry_count"] == 0
        assert committed["last_error"] is None
        assert committed["processed_at"] is None
        assert {
            key: value
            for key, value in committed.items()
            if key not in {"status", "claimed_at"}
        } == {
            key: value
            for key, value in original.items()
            if key not in {"status", "claimed_at"}
        }
        async with env["factory"].begin() as recovery:
            pid_b = await recovery.scalar(text("select pg_backend_pid()"))
            assert pid_a != pid_b
            record_property("abandon_recovery_backend_pids", f"{pid_a},{pid_b}")
            assert (
                await repos["financial_delivery_repo"].claim_pending_events(
                    1000, session=recovery
                )
                == []
            )
        await processor.process_once()
        assert request_state(env, before[2][0]) == committed
        assert durable_state(env) == before
        assert probe.orders == []
        # Only the mutable lease clock is aged. No financial history, identity,
        # status, retry count or control record is rewritten to stage recovery.
        with Session(env["pg"]) as db, db.begin():
            row = db.get(OutboxEventModel, before[2][0])
            row.claimed_at = env["now"] - timedelta(days=1)
        aged = request_state(env, before[2][0])
        assert {k: v for k, v in aged.items() if k != "claimed_at"} == {
            k: v for k, v in committed.items() if k != "claimed_at"
        }
        await processor.process_once()
        assert_negative_delivery(env, before, probe)
        recovered = request_state(env, before[2][0])
        assert recovered["claimed_at"] > aged["claimed_at"]
    finally:
        await engine_a.dispose()
