"""Actual PostgreSQL capture authority, atomicity and historical replay."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_client_entitlement_runtime import (
    capture,
    rows,
    seed_attribution,
)
from tests.postgres_financial.test_client_entitlement_runtime import (
    capture_env as _capture_env,
)
from ugc_bot.application.services.client_entitlement_service import (
    ClientEntitlementService,
)
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.identity_history import (
    SqlAlchemyCreatorIdentityHistoryRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.db.repositories.rate_overrides import (
    SqlAlchemyRateOverrideRepository,
)

capture_env = _capture_env


def consumer(env, *, ledger=None):
    return ClientEntitlementService(
        SqlAlchemyClientEntitlementRepository(),
        ledger or FinancialLedgerService(SqlAlchemyFinancialLedgerRepository()),
        CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(env["factory"])
        ),
        SqlAlchemyRateOverrideRepository(),
        SystemClock(),
    )


async def deliver(env, event_id, *, handler=None, isolation=None):
    async with env["factory"]() as session, session.begin():
        if isolation:
            await session.connection(
                execution_options={"isolation_level": isolation}
            )
        model = await session.get(OutboxEventModel, event_id)
        event = _to_outbox_event_entity(model)
        await (handler or consumer(env)).handle(event, session=session)


def receipt_rows(env):
    return rows(env, "financial_client_assessments")


def assert_no_entitlement(env):
    for name in (
        "financial_obligations",
        "rate_snapshots",
        "financial_movements",
        "financial_client_assessments",
    ):
        assert rows(env, name) == [], name


@pytest.mark.asyncio
async def test_refund_after_receipt_replays_original_assessment(capture_env):
    env = capture_env
    seed_attribution(env)
    event_id = await capture(env)
    await deliver(env, event_id)
    original = receipt_rows(env)
    movements = rows(env, "financial_movements")
    obligations = rows(env, "financial_obligations")
    item = Base.metadata.tables["order_items"]
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(item)
            .where(item.c.order_id == env["order"])
            .values(selection_state="refunded")
        )
    await deliver(env, event_id)
    assert receipt_rows(env) == original
    assert rows(env, "financial_movements") == movements
    assert rows(env, "financial_obligations") == obligations


@pytest.mark.asyncio
async def test_changed_stored_capture_after_receipt_is_idempotency_conflict(
    capture_env,
):
    env = capture_env
    seed_attribution(env)
    event_id = await capture(env)
    await deliver(env, event_id)
    original = receipt_rows(env)
    movements = rows(env, "financial_movements")
    with Session(env["pg"]) as db, db.begin():
        event = db.get(OutboxEventModel, event_id)
        payload = deepcopy(event.payload)
        payload["selection_bases"][0][1] += 1
        event.payload = payload
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await deliver(env, event_id)
    assert receipt_rows(env) == original
    assert rows(env, "financial_movements") == movements


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "intent",
        "base",
        "paid_at",
        "registration",
        "capture_policy",
        "payment_id",
        "receipt_external_id",
        "account",
        "capture_source",
    ],
)
async def test_mutated_capture_authority_cannot_issue_money(
    capture_env, mutation
):
    env = capture_env
    seed_attribution(env, years=2 if mutation == "registration" else 0)
    event_id = await capture(env)
    with Session(env["pg"]) as db, db.begin():
        event = db.get(OutboxEventModel, event_id)
        payload = deepcopy(event.payload)
        if mutation == "intent":
            intent = db.scalar(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id == str(env["order"]),
                    OutboxEventModel.event_type == "financial.capture_intent",
                )
            )
            intent.payload = dict(intent.payload, amount_minor=1)
        elif mutation == "base":
            payload["selection_bases"][0][1] += 100
        elif mutation == "paid_at":
            # paid_at remains mutable in the canonical payment schema;
            # it must still agree with immutable item/capture timestamps.
            payment = Base.metadata.tables["payments"]
            db.execute(
                update(payment)
                .where(payment.c.order_id == env["order"])
                .values(paid_at=env["now"] + timedelta(minutes=2))
            )
        elif mutation == "registration":
            # Raising an older client's rate from 3% to 10% by forging a
            # younger date must fail against immutable registration history.
            payload["client_registered_at"] = (
                env["now"] - timedelta(days=1)
            ).isoformat()
        elif mutation == "capture_policy":
            payload["capture"]["policy_version"] = str(uuid4())
        elif mutation == "payment_id":
            payload["payment_id"] = str(uuid4())
        elif mutation == "receipt_external_id":
            payload["capture"]["external_id"] = "forged-charge"
        elif mutation == "account":
            payload["capture"]["account"] = "another-merchant"
        else:
            payload["capture"]["captured_at_source"] = "request.body"
        event.payload = payload
    with pytest.raises(ValueError):
        await deliver(env, event_id)
    assert_no_entitlement(env)


class InjectedFailure(RuntimeError):
    pass


class FailAfterFirstIssuance(FinancialLedgerService):
    async def issue(self, basis, *, recorded_at, session):
        await super().issue(basis, recorded_at=recorded_at, session=session)
        raise InjectedFailure("after_first_real_issuance")


@pytest.mark.asyncio
async def test_failure_after_first_real_issuance_rolls_back_entire_capture(
    capture_env,
):
    env = capture_env
    partner, _ = seed_attribution(env)
    event_id = await capture(env)
    ledger = FailAfterFirstIssuance(SqlAlchemyFinancialLedgerRepository())
    with pytest.raises(InjectedFailure):
        await deliver(env, event_id, handler=consumer(env, ledger=ledger))
    assert_no_entitlement(env)
    wallet = Base.metadata.tables["financial_wallets"]
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(wallet).where(wallet.c.recipient_id == partner)
            ).first()
            is None
        )
    # The paid funding survives: only the consumer's transaction rolled back.
    with Session(env["pg"]) as db:
        payment = Base.metadata.tables["payments"]
        assert (
            db.scalar(
                select(payment.c.captured_minor).where(
                    payment.c.order_id == env["order"]
                )
            )
            == 220000
        )
    await deliver(env, event_id)
    assert len(rows(env, "financial_obligations")) == 2
    assert len(rows(env, "financial_movements")) == 2
    assert len(receipt_rows(env)) == 1


@pytest.mark.asyncio
async def test_duplicate_direct_consumer_delivery_preserves_single_receipt(
    capture_env,
):
    env = capture_env
    seed_attribution(env)
    event_id = await capture(env)
    await deliver(env, event_id)
    original = receipt_rows(env)
    await deliver(env, event_id)
    assert receipt_rows(env) == original
    assert len(rows(env, "financial_obligations")) == 2
    assert len(rows(env, "financial_movements")) == 2
    assert len(rows(env, "rate_snapshots")) == 2


@pytest.mark.asyncio
async def test_missing_history_fails_closed_without_money(capture_env):
    env = capture_env
    seed_attribution(env)
    event_id = await capture(env)
    handler = consumer(env)
    async with env["factory"]() as session, session.begin():
        await session.execute(
            text(
                "ALTER TABLE creator_identity_coverage "
                "RENAME TO hidden_capture_coverage"
            )
        )
        event = _to_outbox_event_entity(
            await session.get(OutboxEventModel, event_id)
        )
        with pytest.raises(ValueError, match="coverage"):
            await handler.handle(event, session=session)
        await session.rollback()
    assert_no_entitlement(env)


@pytest.mark.asyncio
async def test_repeatable_read_cannot_freeze_a_stale_capture(capture_env):
    env = capture_env
    seed_attribution(env)
    event_id = await capture(env)
    with pytest.raises(ValueError, match="read_committed"):
        await deliver(env, event_id, isolation="REPEATABLE READ")
    assert_no_entitlement(env)
