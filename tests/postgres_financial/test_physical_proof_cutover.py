"""Actual P01 proof cutover in private PostgreSQL; no bank transport."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)
from tests.helpers.physical_proofs import payout_facts, pre_cutover_factory
from tests.postgres_financial import test_payout_runtime as runtime
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
)
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofOwner,
    PhysicalProofUnavailable,
)
from ugc_bot.container.payout_factory import build_payout_service
from ugc_bot.infrastructure.db.repositories.payouts import (
    SqlAlchemyPayoutRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    PROOFS,
    SqlAlchemyPhysicalProofRepository,
)


def authority(env):
    return SqlAlchemyPhysicalProofRepository(
        "synthetic-bank-source",
        "synthetic-origin-account",
        env["service"].clock,
    )


def proof(env, command):
    return authority(env).resolve_manual_identity(
        command.bank_account, command.bank_reference, direction="outgoing"
    )


def claims(env):
    with Session(env["pg"]) as db:
        return tuple(db.execute(select(PROOFS)).mappings())


@pytest.mark.asyncio
async def test_absent_authority_never_guesses_a_bank_namespace():
    repository = SqlAlchemyPayoutRepository(None)
    with pytest.raises(PhysicalProofUnavailable):
        await repository.bank_reference_lock("label", "proof", session=object())


@pytest.mark.asyncio
async def test_compatibility_lock_and_receipt_read_use_the_shared_owner(
    payout_env,
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    await env["execute"](command)
    repository = env["service"].repository
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        await repository.bank_reference_lock(
            command.bank_account, command.bank_reference, session=db
        )
        assert (
            await repository.receipt_used(
                command.bank_account,
                command.bank_reference,
                request_id=UUID(state["request_id"]),
                execution_id=UUID(state["execution_id"]),
                session=db,
            )
            is None
        )
        assert await repository.receipt_used(
            command.bank_account,
            command.bank_reference,
            request_id=uuid4(),
            execution_id=uuid4(),
            session=db,
        ) == UUID(state["execution_id"])


@pytest.mark.asyncio
async def test_direction_is_part_of_the_actual_claim_key(payout_env):
    env = payout_env
    repository = authority(env)
    identity = repository.resolve_manual_identity(
        "synthetic-origin-account",
        "synthetic:" + str(uuid4()),
        direction="incoming",
    )
    owner = PhysicalProofOwner(
        producer="repayment",
        intent_id=uuid4(),
        observation_id=uuid4(),
        command_id=uuid4(),
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        assert await repository.owners(identity, session=db) == ()
        assert await repository.claim(identity, owner, session=db) == owner
        assert await repository.owners(identity, session=db) == (owner,)
        assert (
            await repository.claim(
                identity, replace(owner, observation_id=uuid4()), session=db
            )
            == owner
        )
        outgoing = replace(identity, direction="outgoing")
        assert await repository.owners(outgoing, session=db) == ()


@pytest.mark.asyncio
async def test_paid_observation_claim_has_actual_preallocated_receipt(
    payout_env,
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    result = await env["execute"](command)
    assert result["state"] == "paid"
    facts = payout_facts(env["pg"])
    outcome = next(
        row
        for row in facts["outcomes"]
        if row["execution_id"] == UUID(state["execution_id"])
    )
    receipt = next(
        row
        for row in facts["commands"]
        if row["operation_key"] == command.operation_key
    )
    own = [
        row
        for row in claims(env)
        if row["intent_id"] == outcome["execution_id"]
    ]
    assert len(own) == 1
    assert own[0]["observation_id"] == outcome["outcome_id"]
    assert own[0]["command_id"] == receipt["command_id"]
    before = payout_facts(env["pg"])
    assert await env["execute"](command) == result
    assert payout_facts(env["pg"]) == before


@pytest.mark.asyncio
async def test_refund_claim_prevents_payout_but_retains_actual_outcome(
    payout_env,
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    owner = PhysicalProofOwner(
        producer="refund",
        intent_id=uuid4(),
        observation_id=uuid4(),
        command_id=uuid4(),
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        assert (
            await authority(env).claim(proof(env, command), owner, session=db)
            == owner
        )
    result = await env["execute"](command)
    assert result["state"] == "unknown"
    assert result["block_reason"] == "payout_bank_reference_reused"
    assert any(
        row["bank_reference"] == command.bank_reference and not row["applied"]
        for row in payout_facts(env["pg"])["outcomes"]
    )
    assert (
        next(row for row in claims(env) if row["intent_id"] == owner.intent_id)[
            "producer"
        ]
        == "refund"
    )


@pytest.mark.asyncio
async def test_missing_source_denies_start_without_implicit_origin(payout_env):
    env = payout_env
    state = await env["execute"](request_command(env))
    state = await env["execute"](review_command(env, state, "review"))
    env["config"].financial.manual_bank_source_id = ""
    with pytest.raises(
        ValueError, match="^payout_bank_source_configuration_required$"
    ):
        await env["execute"](review_command(env, state, "start"))
    assert not [
        row
        for row in payout_facts(env["pg"])["intents"]
        if row["request_id"] == UUID(state["request_id"])
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("conflicting", [False, True])
async def test_real_old_parent_producer_survives_upgrade(
    user_repo, advertiser_repo, monkeypatch, conflicting, request
):
    old_factory = pre_cutover_factory()
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
        current_order_model=True,
    ) as engine:
        capture = asynccontextmanager(capture_env.__wrapped__)
        payout = asynccontextmanager(payout_env.__wrapped__)
        with monkeypatch.context() as patch:
            patch.setattr(runtime, "build_payout_service", old_factory)
            async with (
                capture(
                    engine, user_repo, advertiser_repo, request
                ) as captured,
                payout(captured, patch) as env,
            ):
                amount = 20000 if conflicting else 30000
                paid = await prepare(env, amount=amount)
                second = await prepare(env, amount=amount, key="old:second")
                third = (
                    await prepare(env, amount=amount, key="old:third")
                    if conflicting
                    else None
                )
                paid_command = result_command(env, paid)
                assert (await env["execute"](paid_command))["state"] == "paid"
                unapplied = result_command(env, second, expected_version=0)
                assert (await env["execute"](unapplied))["state"] == "unknown"
                if conflicting:
                    conflict = await env["execute"](
                        result_command(
                            env,
                            third,
                            bank_reference=paid_command.bank_reference,
                        )
                    )
                    assert (
                        conflict["block_reason"]
                        == "payout_bank_reference_reused"
                    )
                before = payout_facts(engine)
                with engine.connect() as db:
                    assert (
                        db.scalar(
                            text(
                                "SELECT to_regclass("
                                "'financial_physical_proof_claims')"
                            )
                        )
                        is None
                    )
                upgrade_financial_schema(
                    engine, target_revision="financial_corrections_a1"
                )
                assert payout_facts(engine) == before
                assert not claims(env)
                for command, intent in (
                    (paid_command, paid),
                    (unapplied, second),
                ):
                    async with env["flow"][
                        "container"
                    ].transaction_manager.transaction() as db:
                        owners = await authority(env).owners(
                            proof(env, command), session=db
                        )
                        assert len(owners) == (
                            2 if conflicting and intent == paid else 1
                        )
                        actual = next(
                            owner
                            for owner in owners
                            if owner.intent_id == UUID(intent["execution_id"])
                        )
                        observed = next(
                            row
                            for row in before["outcomes"]
                            if row["execution_id"] == actual.intent_id
                        )
                        receipt = next(
                            row
                            for row in before["commands"]
                            if row["operation_key"] == command.operation_key
                        )
                        assert actual.observation_id == observed["outcome_id"]
                        assert actual.command_id == receipt["command_id"]
                        if len(owners) > 1:
                            with pytest.raises(PhysicalProofConflict):
                                await authority(env).claim(
                                    proof(env, command), actual, session=db
                                )
                        else:
                            assert (
                                await authority(env).claim(
                                    proof(env, command), actual, session=db
                                )
                                == actual
                            )
                        with pytest.raises(PhysicalProofConflict):
                            await authority(env).claim(
                                proof(env, command),
                                PhysicalProofOwner(
                                    producer="refund",
                                    intent_id=uuid4(),
                                    observation_id=uuid4(),
                                    command_id=uuid4(),
                                ),
                                session=db,
                            )
                assert payout_facts(engine) == before
                assert not claims(env)
                container = env["flow"]["container"]
                current = build_payout_service(
                    env["config"],
                    container.transaction_manager,
                    container.session_factory,
                )
                async with container.transaction_manager.transaction() as db:
                    replay = await current.execute(paid_command, session=db)
                old = next(
                    row
                    for row in before["commands"]
                    if row["operation_key"] == paid_command.operation_key
                )
                assert replay == old["result"]
                assert payout_facts(engine) == before and not claims(env)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["emergency", "key", "stale", "savepoint"])
async def test_paid_proof_survives_expected_money_refusal(
    payout_env, monkeypatch, case
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    if case == "emergency":
        env["config"].financial.payouts_enabled = False
    elif case == "key":
        env["service"].crypto = None
    elif case == "stale":
        command = replace(command, expected_version=0)
    else:
        original = env["service"].repository.add

        async def duplicate(name, values, *, session):
            await original(name, values, session=session)
            if name == "settlements":
                await original(name, values, session=session)

        monkeypatch.setattr(env["service"].repository, "add", duplicate)
    result = await env["execute"](command)
    assert result["state"] == "unknown"
    owned = next(
        row
        for row in claims(env)
        if row["intent_id"] == UUID(state["execution_id"])
    )
    observed = next(
        row
        for row in payout_facts(env["pg"])["outcomes"]
        if row["outcome_id"] == owned["observation_id"]
    )
    assert observed["status"] == "paid" and not observed["applied"]
    assert not [
        row
        for row in payout_facts(env["pg"])["settlements"]
        if row["execution_id"] == owned["intent_id"]
    ]
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        with pytest.raises(PhysicalProofConflict):
            await authority(env).claim(
                proof(env, command),
                PhysicalProofOwner(
                    producer="refund",
                    intent_id=uuid4(),
                    observation_id=uuid4(),
                    command_id=uuid4(),
                ),
                session=db,
            )


@pytest.mark.asyncio
async def test_same_execution_reconciliation_returns_original_owner(payout_env):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state, expected_version=0)
    unknown = await env["execute"](command)
    original = next(
        row
        for row in claims(env)
        if row["intent_id"] == UUID(state["execution_id"])
    )
    paid = await env["execute"](
        replace(
            command,
            operation_key="reconcile:actual",
            expected_version=unknown["version"],
        )
    )
    assert paid["state"] == "paid"
    assert (
        next(
            row
            for row in claims(env)
            if row["intent_id"] == original["intent_id"]
        )
        == original
    )
    actual = [
        row
        for row in payout_facts(env["pg"])["outcomes"]
        if row["execution_id"] == original["intent_id"]
    ]
    assert len(actual) == 2 and sum(row["applied"] for row in actual) == 1


@pytest.mark.asyncio
async def test_outer_failure_rolls_back_claim_outcome_and_receipt(
    payout_env, monkeypatch
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    before, owned = payout_facts(env["pg"]), claims(env)
    original = env["service"].repository.add

    async def fail(name, values, *, session):
        await original(name, values, session=session)
        if name == "commands" and values["action"] == "RecordPayoutResult":
            raise RuntimeError("synthetic_outer_receipt_failure")

    monkeypatch.setattr(env["service"].repository, "add", fail)
    with pytest.raises(RuntimeError, match="synthetic_outer_receipt_failure"):
        await env["execute"](command)
    assert payout_facts(env["pg"]) == before
    assert claims(env) == owned


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_source", "unknown_account"])
async def test_unrecognized_actual_proof_is_retained_unavailable(
    payout_env, case
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    if case == "missing_source":
        env["config"].financial.manual_bank_source_id = ""
        container = env["flow"]["container"]
        env["service"] = build_payout_service(
            env["config"],
            container.transaction_manager,
            container.session_factory,
        )
    else:
        command = replace(command, bank_account="unrecognized-actual-account")
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        result = await env["service"].execute(command, session=db)
    assert result["state"] == "unknown"
    assert result["block_reason"] == (
        "payout_bank_reconciliation_required"
        if case == "missing_source"
        else "payout_bank_account_mismatch"
    )
    assert not [
        row
        for row in claims(env)
        if row["intent_id"] == UUID(state["execution_id"])
    ]
    observed = next(
        row
        for row in payout_facts(env["pg"])["outcomes"]
        if row["execution_id"] == UUID(state["execution_id"])
    )
    assert observed["bank_account"] == command.bank_account
    assert not observed["applied"]
    if case == "unknown_account":
        async with env["flow"][
            "container"
        ].transaction_manager.transaction() as db:
            with pytest.raises(PhysicalProofUnavailable):
                await authority(env).owners(
                    proof(
                        env,
                        result_command(
                            env, state, bank_reference=command.bank_reference
                        ),
                    ),
                    session=db,
                )


async def wait_for_advisory(factory, pid):
    async with factory() as observer:
        for _ in range(100):
            waiting = await observer.scalar(
                text("SELECT wait_event FROM pg_stat_activity WHERE pid=:pid"),
                {"pid": pid},
            )
            if waiting == "advisory":
                return
            await asyncio.sleep(0.01)
    raise AssertionError("actual shared proof mutex did not block")


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["payout", "refund"])
async def test_distinct_backend_producers_share_the_same_mutex(
    payout_env, first
):
    env = payout_env
    state = await prepare(env)
    command = result_command(env, state)
    engine = create_async_engine(env["pg"].url, pool_size=3, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = PhysicalProofOwner(
        producer="refund",
        intent_id=uuid4(),
        observation_id=uuid4(),
        command_id=uuid4(),
    )
    pid_ready = asyncio.Future()

    async def second():
        async with factory.begin() as db:
            pid_ready.set_result(
                await db.scalar(text("SELECT pg_backend_pid()"))
            )
            if first == "payout":
                with pytest.raises(PhysicalProofConflict):
                    await authority(env).claim(
                        proof(env, command), owner, session=db
                    )
                return None
            return await env["service"].execute(command, session=db)

    task = None
    try:
        async with factory.begin() as db:
            first_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            if first == "payout":
                assert (await env["service"].execute(command, session=db))[
                    "state"
                ] == "paid"
            else:
                assert (
                    await authority(env).claim(
                        proof(env, command), owner, session=db
                    )
                    == owner
                )
            task = asyncio.create_task(second())
            second_pid = await asyncio.wait_for(pid_ready, 5)
            assert first_pid != second_pid
            await wait_for_advisory(factory, second_pid)
            print(
                f"shared-proof first={first} pids={first_pid},{second_pid} "
                "wait=advisory"
            )
        result = await asyncio.wait_for(task, 5)
        if first == "refund":
            assert result["state"] == "unknown"
            assert result["block_reason"] == "payout_bank_reference_reused"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
