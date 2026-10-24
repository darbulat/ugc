"""Preserved foundation v1 bank references are readable, never payout proof."""

import base64
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)
from tests.helpers.payout_contracts import acceptance_fields, publication_fields
from tests.helpers.repositories import create_in_memory_repositories
from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)
from tests.postgres_financial.test_payout_runtime import (
    prepare,
    request_command,
    result_command,
    review_command,
    rows,
)
from tests.postgres_financial.test_work_entitlement_runtime import (
    finish_work,
    process_work_events,
    start_flow,
    wallet,
)
from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    StorePayoutRequisites,
)
from ugc_bot.container.payout_factory import build_payout_service
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import PayoutRequestModel, UserModel
from ugc_bot.infrastructure.db.repositories.financial_ledger import payload_hash
from ugc_bot.infrastructure.db.repositories.payouts import (
    SqlAlchemyPayoutRepository,
)

__all__ = ["capture_env", "payout_env"]
STOP = "payout_history_authority_review_required"


async def foundation_history(env, target, *, amount=30000):
    """Synthetic pre-P01 boundary, with no invented authority."""
    owner, flow = env["flow"]["manager"], env["flow"]
    repo = SqlAlchemyPayoutRepository(flow["container"].session_factory)
    request, allocation, execution = uuid4(), uuid4(), uuid4()
    async with flow["container"].transaction_manager.transaction() as db:
        await repo.lock_users((env["client"], owner), session=db)
        obligations = await repo.lock_money_scope(owner, session=db)
        obligation = obligations[0]["id"]
        # This also runs before the protocol column exists.
        await db.execute(
            insert(PayoutRequestModel.__table__).values(
                request_id=request,
                user_id=owner,
                amount=Decimal(amount) / 100,
                currency="RUB",
                status="pending",
                requested_at=flow["clock"].at,
                updated_at=flow["clock"].at,
            )
        )
        shapes = [("available", "reserved")]
        if target == "paid":
            shapes.append(("reserved", "paid"))
        for source, destination in shapes:
            movement = JournalMovement(
                obligation_id=obligation,
                operation_key="synthetic-foundation:" + str(uuid4()),
                event_id="synthetic-foundation-history",
                movement_type="transfer",
                amount_minor=amount,
                currency="RUB",
                effective_at=flow["clock"].at,
                recorded_at=flow["clock"].at,
                actor_id=env["client"],
                actor_kind="admin",
                reason="Synthetic preserved foundation UUIDs, no bank approval",
                bucket_from=source,
                bucket_to=destination,
                request_id=request,
                allocation_id=allocation,
                execution_id=execution if destination == "paid" else None,
            )
            values = asdict(movement)
            await db.execute(
                insert(Base.metadata.tables["financial_movements"]).values(
                    **values, id=uuid4(), payload_hash=payload_hash(values)
                )
            )
            await repo.ledger.apply_projection(movement, session=db)
    return request


def journal(env):
    movements = Base.metadata.tables["financial_movements"]
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        return [
            dict(r)
            for r in db.execute(
                select(movements)
                .join(
                    obligations, obligations.c.id == movements.c.obligation_id
                )
                .where(obligations.c.recipient_id == env["flow"]["manager"])
                .order_by(movements.c.append_order)
            ).mappings()
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["reserved", "paid"])
async def test_unproven_foundation_history_blocks_new_reserve_but_is_readable(
    payout_env, target
):
    env = payout_env
    request = await foundation_history(env, target)
    before = journal(env)
    with pytest.raises(ValueError, match=STOP):
        await env["execute"](request_command(env, amount_minor=30000))
    assert journal(env) == before
    assert not [
        r
        for r in rows(env, "requests")
        if r["recipient_id"] == env["flow"]["manager"]
    ]
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        repo = env["service"].repository
        await repo.lock_users((env["flow"]["manager"],), session=db)
        await repo.lock_money_scope(env["flow"]["manager"], session=db)
        replay = await repo.reconcile_locked(env["flow"]["manager"], session=db)
        assert replay.balanced and replay.balances["available"] == 30000
        entries = await repo.ledger.list_for_recipient(
            env["flow"]["manager"], "RUB", session=db
        )
        assert any(m.request_id == request for m in entries)
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 30000


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["reserved", "paid"])
@pytest.mark.parametrize("action", ["review", "start"])
async def test_unproven_history_blocks_existing_review_and_start(
    payout_env, target, action
):
    env = payout_env
    state = await env["execute"](request_command(env, amount_minor=10000))
    if action == "start":
        state = await env["execute"](review_command(env, state, "review"))
    await foundation_history(env, target, amount=20000)
    before = journal(env)
    result = await env["execute"](review_command(env, state, action))
    assert result["state"] == "blocked" and result["block_reason"] == STOP
    assert journal(env) == before
    assert not [
        r
        for r in rows(env, "intents")
        if str(r["request_id"]) == state["request_id"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["reserved", "paid"])
async def test_history_readiness_refusal_retains_bank_fact_claim_and_replay(
    payout_env, target
):
    env = payout_env
    state = await prepare(env, 10000)
    await foundation_history(env, target, amount=20000)
    before = journal(env)
    command = result_command(env, state, amount_minor=10000)
    result = await env["execute"](command)
    assert result["state"] == "unknown" and result["block_reason"] == STOP
    assert await env["execute"](command) == result
    facts = [
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == state["request_id"]
    ]
    assert len(facts) == 1 and not facts[0]["applied"]
    assert facts[0]["bank_reference"] == command.bank_reference
    assert facts[0]["evidence_hash"] == command.evidence_hash
    assert not [
        r
        for r in rows(env, "settlements")
        if str(r["request_id"]) == state["request_id"]
    ]
    with pytest.raises(ValueError, match=STOP):
        await env["execute"](
            request_command(
                env, operation_key="new-after-history", amount_minor=1000
            )
        )
    repeated = await env["execute"](
        replace(
            command,
            operation_key="fresh-history-observation",
            expected_version=result["version"],
        )
    )
    assert repeated["state"] == "unknown" and repeated["block_reason"] == STOP
    assert journal(env) == before
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        repo = env["service"].repository
        assert await repo.receipt_used(
            command.bank_account,
            command.bank_reference,
            request_id=uuid4(),
            execution_id=uuid4(),
            session=db,
        ) == UUID(state["execution_id"])
        visible = await env["service"].get_for_actor(
            UUID(state["request_id"]), env["flow"]["manager"], session=db
        )
        assert visible["state"] == "unknown"


@pytest.mark.asyncio
async def test_true_legacy_only_payout_row_does_not_block_v1_readiness(
    payout_env,
):
    env = payout_env
    with Session(env["pg"]) as db, db.begin():
        db.add(
            PayoutRequestModel(
                request_id=uuid4(),
                user_id=env["flow"]["manager"],
                amount=Decimal("123.45"),
                currency="RUB",
                status="paid",
                requested_at=env["flow"]["clock"].at,
            )
        )
    assert (await prepare(env))["state"] == "executing"


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["reserved", "paid"])
async def test_populated_foundation_upgrade_preserves_history_and_stops_money(
    monkeypatch, target
):
    """Actual old-schema history survives upgrade without fabricated parents."""
    repositories = create_in_memory_repositories()
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_foundation_v1",
    ) as engine:
        async with asynccontextmanager(capture_env.__wrapped__)(
            engine, repositories.user_repo, repositories.advertiser_repo
        ) as capture:
            flow = await start_flow(capture, monkeypatch)
            try:
                await finish_work(capture, flow)
                await process_work_events(capture, flow)
                flow["clock"].at += timedelta(days=14)
                await flow["command"](
                    "advance", None, 4, system_actor="collaboration_scheduler"
                )
                await process_work_events(capture, flow)
                env = capture | {"flow": flow}
                assert wallet(env, flow["manager"])["available_minor"] == 60000
                old_request = await foundation_history(env, target)
                before = journal(env)
                upgrade_financial_schema(
                    engine, target_revision="financial_payout_v1"
                )
                assert journal(env) == before
                with Session(engine) as db, db.begin():
                    old = db.get(PayoutRequestModel, old_request)
                    assert (
                        old.payout_protocol is None
                        and old.amount == Decimal("300")
                    )
                    db.execute(
                        update(UserModel)
                        .where(UserModel.user_id == env["client"])
                        .values(admin=True)
                    )
                upgrade_financial_schema(
                    engine, target_revision="financial_payout_contracts_v1"
                )
                config = flow["container"]._config
                config.financial.payouts_enabled = True
                config.financial.requisites_key = SecretStr(
                    base64.urlsafe_b64encode(os.urandom(32)).decode()
                )
                config.financial.requisites_key_id = "synthetic-migration-key"
                service = build_payout_service(
                    config,
                    flow["container"].transaction_manager,
                    flow["container"].session_factory,
                )
                service.clock = type(
                    "Clock", (), {"now": lambda self: flow["clock"].at}
                )()

                async def execute(command):
                    async with flow[
                        "container"
                    ].transaction_manager.transaction() as db:
                        return await service.execute(command, session=db)

                publication = await execute(
                    PublishPayoutRequirements(
                        actor_id=env["client"],
                        operation_key="post-upgrade-publication",
                        reason="Synthetic boundary; no legal approval",
                        expected_version=0,
                        effective_from=flow["clock"].at,
                        legal_reference="synthetic:migration-legal",
                        terms_reference="synthetic:migration-terms",
                        evidence_reference="synthetic:migration-proof",
                        required_fields=(
                            "recipient_name",
                            "bank_account",
                            "legal_status",
                        ),
                        **publication_fields(),
                    )
                )
                details = await execute(
                    StorePayoutRequisites(
                        actor_id=flow["manager"],
                        operation_key="post-upgrade-details",
                        requirements_id=publication["requirements_id"],
                        accepted_terms_reference="synthetic:migration-terms",
                        details={
                            "recipient_name": "Synthetic",
                            "bank_account": "123456",
                            "legal_status": "synthetic",
                        },
                        **acceptance_fields(publication),
                    )
                )
                env |= dict(
                    service=service, execute=execute, requisites=details
                )
                with pytest.raises(ValueError, match=STOP):
                    await execute(request_command(env, amount_minor=30000))
                assert journal(env) == before
                assert rows(env, "allocations") == []
                assert rows(env, "settlements") == []
            finally:
                await flow["container"].dispose()


@pytest.mark.asyncio
async def test_accepted_p01_paid_history_keeps_remaining_funds_ready(
    payout_env,
):
    env = payout_env
    first = await prepare(env, 30000)
    settled = await env["execute"](
        result_command(env, first, amount_minor=30000)
    )
    assert settled["state"] == "paid"
    second = await prepare(env, 30000, key="after-accepted-paid")
    assert second["state"] == "executing"
    balance = wallet(env, env["flow"]["manager"])
    assert balance["paid_minor"] == 30000
    assert balance["reserved_minor"] == 30000
