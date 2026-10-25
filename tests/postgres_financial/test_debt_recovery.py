"""Incoming bank proof recovers an actual paid ground without rewriting it."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as _payout_env,
)
from tests.postgres_financial.test_payout_runtime import (
    prepare,
    result_command,
    wallet,
)
from ugc_bot.application.debt_recovery_ports import (
    ApplyDebtRecovery,
    RecordDebtRepayment,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.container.debt_recovery_factory import build_debt_recovery
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.debt_recovery_models import (
    APPLICATIONS,
    COMMANDS,
    OBSERVATIONS,
)

payout_env = _payout_env


async def prepared(env):
    state = await prepare(env)
    paid = await env["execute"](result_command(env, state))
    assert paid["state"] == "paid"
    recovery = build_debt_recovery(env["config"])
    recovery.clock = env["service"].clock
    recovery.physical_proofs.clock = recovery.clock
    tm = env["flow"]["container"].transaction_manager
    with Session(env["pg"]) as db:
        business_key = db.scalar(
            select(
                Base.metadata.tables["financial_obligations"].c.business_key
            ).where(
                Base.metadata.tables["financial_obligations"].c.recipient_id
                == env["flow"]["manager"]
            )
        )
    case = uuid4()
    async with tm.transaction() as db:
        issue = await recovery.ledger.repository.get_issue(
            business_key, session=db
        )
        await recovery.ledger.repository.lock_recipients(
            tuple(sorted((env["client"], issue.basis.recipient_id), key=str)),
            session=db,
        )
        # Trusted fixture starts after refund authority was established. P01
        # above supplies genuine paid history; this is not a real bank pilot.
        await ObligationCompensationService(recovery.ledger).cancel(
            issue,
            target_minor=30000,
            already_cancelled_minor=0,
            case_id=case,
            refund_id=uuid4(),
            actor_id=env["client"],
            now=recovery.clock.now(),
            session=db,
        )
    observation = RecordDebtRepayment(
        actor_id=env["client"],
        operation_key="incoming:" + uuid4().hex,
        recipient_id=env["flow"]["manager"],
        case_id=case,
        amount_minor=20000,
        currency="RUB",
        bank_account_label="synthetic-origin-account",
        bank_reference="synthetic-repayment:" + uuid4().hex,
        occurred_at=recovery.clock.now(),
        reason="Synthetic bank evidence review",
        evidence_reference="synthetic:statement-not-real-repayment",
        evidence_hash="b" * 64,
    )

    async def execute(command):
        async with tm.transaction() as db:
            method = (
                recovery.observe
                if isinstance(command, RecordDebtRepayment)
                else recovery.apply
            )
            return await method(command, session=db)

    return recovery, execute, observation, business_key, tm


def applying(observation, receipt, business_key, **changes):
    return ApplyDebtRecovery(
        **(
            dict(
                actor_id=observation.actor_id,
                operation_key="apply:" + uuid4().hex,
                observation_id=UUID(receipt["observation_id"]),
                business_key=business_key,
                case_id=observation.case_id,
                expected_debt_minor=30000,
                reason="Separate review of incoming funds",
                evidence_reference="synthetic:statement",
                evidence_hash="c" * 64,
            )
            | changes
        )
    )


@pytest.mark.asyncio
async def test_actual_paid_recovery_concurrency_and_immutable_source(
    payout_env,
):
    env = payout_env
    recovery, execute, observation, key, tm = await prepared(env)
    receipt = await execute(observation)
    assert receipt["proof_claimed"] and not receipt["applied"]
    command = applying(observation, receipt, key)
    results = await asyncio.gather(execute(command), execute(command))
    assert results[0] == results[1]
    assert results[0]["remaining_debt_minor"] == 10000
    balances = wallet(env, env["flow"]["manager"])
    assert balances["paid_minor"] == 60000
    assert balances["debt_minor"] == 10000
    assert balances["available_minor"] == 0
    async with tm.transaction() as db:
        context = await recovery.context(env["client"], session=db)
    assert any(
        row["business_key"] == key and row["debt_minor"] == 10000
        for row in context["cases"]
    )
    assert any(
        row["application_id"]
        for row in context["observations"]
        if str(row["observation_id"]) == receipt["observation_id"]
    )
    for table in (COMMANDS, OBSERVATIONS, APPLICATIONS):
        with (
            Session(env["pg"]) as db,
            pytest.raises(DBAPIError, match="immutable"),
        ):
            db.execute(text(f"DELETE FROM {table.name}"))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            text("UPDATE users SET admin=false WHERE user_id=:id"),
            {"id": env["client"]},
        )
    with pytest.raises(PermissionError, match="active_admin"):
        await execute(command)


@pytest.mark.asyncio
async def test_physical_incoming_proof_cannot_be_reused_or_overrecover(
    payout_env,
):
    env = payout_env
    _, execute, observation, key, _ = await prepared(env)
    receipt = await execute(replace(observation, amount_minor=40000))
    with pytest.raises(ValueError, match="exceeds"):
        await execute(applying(observation, receipt, key))
    other = await execute(
        replace(observation, operation_key="duplicate-proof:" + uuid4().hex)
    )
    assert not other["proof_claimed"] and not other["applied"]
    with pytest.raises(ValueError, match="physical_proof_required"):
        await execute(applying(observation, other, key))
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(APPLICATIONS.c.application_id).where(
                    APPLICATIONS.c.observation_id
                    == UUID(receipt["observation_id"])
                )
            )
            is None
        )
    assert wallet(env, env["flow"]["manager"])["debt_minor"] == 30000


@pytest.mark.asyncio
async def test_recovery_sql_source_seal_rolls_back_tampered_application(
    payout_env, monkeypatch
):
    env = payout_env
    recovery, execute, observation, key, _ = await prepared(env)
    receipt = await execute(observation)
    save = recovery.repository.append_application

    async def tampered(value, *, session):
        await save(
            dict(value, amount_minor=value["amount_minor"] + 1), session=session
        )

    monkeypatch.setattr(recovery.repository, "append_application", tampered)
    with pytest.raises(DBAPIError, match="source_mismatch"):
        await execute(applying(observation, receipt, key))
    assert wallet(env, env["flow"]["manager"])["debt_minor"] == 30000
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(APPLICATIONS.c.application_id).where(
                    APPLICATIONS.c.observation_id
                    == UUID(receipt["observation_id"])
                )
            )
            is None
        )
    monkeypatch.setattr(recovery.repository, "append_application", save)
    assert (await execute(applying(observation, receipt, key)))[
        "remaining_debt_minor"
    ] == 10000


@pytest.mark.asyncio
async def test_one_actual_incoming_partially_recovers_two_paid_case_grounds(
    payout_env,
):
    from tests.helpers.debt_batch_pg import paid_batch_case

    env = payout_env
    batch = await paid_batch_case(env)
    execute, observation = batch["execute"], batch["observation"]
    receipt = await execute(observation)
    command = applying(
        observation, receipt, batch["business_key"], expected_debt_minor=35000
    )
    results = await asyncio.gather(execute(command), execute(command))
    result = results[0]
    assert result == results[1]
    assert result["recovered_minor"] == 34000
    assert result["remaining_debt_minor"] == 1000
    assert len(result["applications"]) == 2
    assert [row["obligation_id"] for row in result["applications"]] == sorted(
        row["obligation_id"] for row in result["applications"]
    )
    with Session(env["pg"]) as db:
        rows = (
            db.execute(
                select(APPLICATIONS).where(
                    APPLICATIONS.c.observation_id == command.observation_id
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2 and sum(row["amount_minor"] for row in rows) == 34000
    assert len({row["command_id"] for row in rows}) == 1
    assert all(row["result"] == result for row in rows)
    balances = wallet(env, observation.recipient_id)
    assert balances["paid_minor"] == batch["paid_minor"] == 72345
    assert balances["debt_minor"] == 1000 and balances["available_minor"] == 0
    async with batch["transactions"].transaction() as db:
        context = await batch["service"].context(
            observation.actor_id, session=db
        )
    cases = [
        row for row in context["cases"] if row["case_id"] == command.case_id
    ]
    assert len(cases) == 1 and cases[0]["debt_minor"] == 1000
    assert (
        len(
            [
                row
                for row in context["observations"]
                if row["observation_id"] == command.observation_id
            ]
        )
        == 1
    )
    later = replace(
        observation,
        operation_key="second-incoming:" + uuid4().hex,
        bank_reference="second-physical-transfer:" + uuid4().hex,
        amount_minor=1000,
    )
    later_receipt = await execute(later)
    final = await execute(
        applying(
            later,
            later_receipt,
            batch["business_key"],
            expected_debt_minor=1000,
        )
    )
    assert final["remaining_debt_minor"] == 0
    assert (await execute(command)) == result
    balances = wallet(env, observation.recipient_id)
    assert balances["paid_minor"] == 72345 and balances["debt_minor"] == 0


@pytest.mark.asyncio
async def test_distinct_incoming_transfers_serialize_against_total_case_debt(
    payout_env,
):
    from tests.helpers.debt_batch_pg import paid_batch_case

    env = payout_env
    batch = await paid_batch_case(env)
    execute = batch["execute"]
    first = replace(batch["observation"], amount_minor=20000)
    second = replace(
        first,
        operation_key="competing incoming:" + uuid4().hex,
        bank_reference="competing physical proof:" + uuid4().hex,
    )
    receipts = [await execute(first), await execute(second)]
    commands = [
        applying(
            fact, receipt, batch["business_key"], expected_debt_minor=35000
        )
        for fact, receipt in zip((first, second), receipts, strict=True)
    ]
    outcomes = await asyncio.gather(
        *(execute(command) for command in commands), return_exceptions=True
    )
    successes = [result for result in outcomes if isinstance(result, dict)]
    failures = [result for result in outcomes if isinstance(result, ValueError)]
    assert len(successes) == len(failures) == 1
    assert successes[0]["remaining_debt_minor"] == 15000
    assert str(failures[0]) == "repayment_debt_version_conflict"
    balances = wallet(env, first.recipient_id)
    assert balances["debt_minor"] == 15000 and balances["paid_minor"] == 72345
    with Session(env["pg"]) as db:
        applications = (
            db.execute(
                select(APPLICATIONS).where(
                    APPLICATIONS.c.case_id == first.case_id
                )
            )
            .mappings()
            .all()
        )
    assert sum(row["amount_minor"] for row in applications) == 20000
    assert len({row["observation_id"] for row in applications}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["noncanonical", "incomplete_group", "late_failure", "case_cas"]
)
async def test_case_group_source_guard_or_failure_rolls_back_all_grounds(
    payout_env, monkeypatch, fault
):
    from tests.helpers.debt_batch_pg import paid_batch_case

    env = payout_env
    batch = await paid_batch_case(env)
    service, execute = batch["service"], batch["execute"]
    observation = batch["observation"]
    receipt = await execute(observation)
    command = applying(
        observation, receipt, batch["business_key"], expected_debt_minor=35000
    )
    allocate, append, save = (
        service._allocate,
        service.repository.append_application,
        service.repository.save_command,
    )
    if fault == "noncanonical":

        async def reordered(*args):
            entries = await allocate(*args)
            assert len(entries) == 2
            (
                (first, first_amount, first_source),
                (last, last_amount, last_source),
            ) = entries
            return [
                (first, first_amount - 1, first_source),
                (last, last_amount + 1, last_source),
            ]

        monkeypatch.setattr(service, "_allocate", reordered)
    elif fault in ("incomplete_group", "late_failure"):
        count = 0

        async def incomplete(value, *, session):
            nonlocal count
            count += 1
            if count == 2:
                if fault == "late_failure":
                    raise RuntimeError("synthetic late transaction failure")
                return
            await append(value, session=session)

        monkeypatch.setattr(
            service.repository, "append_application", incomplete
        )
    else:

        async def stale(value, *, session):
            await save(
                dict(
                    value,
                    payload=dict(value["payload"], expected_debt_minor=35001),
                ),
                session=session,
            )

        monkeypatch.setattr(service.repository, "save_command", stale)
    error, message = (
        (RuntimeError, "late transaction")
        if fault == "late_failure"
        else (DBAPIError, "repayment_")
    )
    with pytest.raises(error, match=message):
        await execute(command)
    balances = wallet(env, observation.recipient_id)
    assert balances["debt_minor"] == 35000 and balances["paid_minor"] == 72345
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(APPLICATIONS.c.application_id).where(
                    APPLICATIONS.c.observation_id == command.observation_id
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(COMMANDS.c.command_id).where(
                    COMMANDS.c.actor_id == command.actor_id,
                    COMMANDS.c.operation_key == command.operation_key,
                )
            )
            is None
        )
        movements = Base.metadata.tables["financial_movements"]
        assert (
            db.scalar(
                select(movements.c.id).where(
                    movements.c.operation_key.like(
                        "repayment:" + str(command.observation_id) + ":%"
                    )
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(OBSERVATIONS.c.observation_id).where(
                    OBSERVATIONS.c.observation_id == command.observation_id
                )
            )
            == command.observation_id
        )
    monkeypatch.setattr(service, "_allocate", allocate)
    monkeypatch.setattr(service.repository, "append_application", append)
    monkeypatch.setattr(service.repository, "save_command", save)
    assert (await execute(command))["remaining_debt_minor"] == 1000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [
        ("occurred_at", None),
        ("occurred_at", "missing"),
        ("evidence_reference", ""),
        ("evidence_hash", "not-a-hash"),
        ("bank_account_label", ""),
        ("bank_reference", ""),
    ],
)
async def test_sql_repayment_observation_requires_time_and_structural_evidence(
    payout_env, monkeypatch, field, value
):
    env = payout_env
    recovery, execute, observation, _, _ = await prepared(env)
    append, save = (
        recovery.repository.append_observation,
        recovery.repository.save_command,
    )

    def changed(document):
        result = dict(document)
        if value == "missing":
            result.pop(field)
        else:
            result[field] = value
        return result

    async def changed_fact(fact, *, session):
        await append(changed(fact), session=session)

    async def changed_command(command, *, session):
        await save(
            dict(command, payload=changed(command["payload"])), session=session
        )

    monkeypatch.setattr(recovery.repository, "append_observation", changed_fact)
    monkeypatch.setattr(recovery.repository, "save_command", changed_command)
    with pytest.raises(
        DBAPIError,
        match="repayment_(observation_source|command_scope)_mismatch",
    ):
        await execute(observation)
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(COMMANDS.c.command_id).where(
                    COMMANDS.c.operation_key == observation.operation_key,
                    COMMANDS.c.actor_id == observation.actor_id,
                )
            )
            is None
        )
        proof = Base.metadata.tables["financial_physical_proof_claims"]
        assert (
            db.scalar(
                select(proof.c.reference).where(
                    proof.c.reference == observation.bank_reference
                )
            )
            is None
        )
    assert wallet(env, observation.recipient_id)["debt_minor"] == 30000


@pytest.mark.asyncio
async def test_empty_repayment_schema_round_trip_and_populated_history_refusal(
    payout_env,
):
    import importlib
    import os

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from tests.helpers.financial_environment import isolated_financial_database

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0115_debt_recovery"
    )
    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="0115_debt_recovery",
        ) as engine,
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
        migration.upgrade()
    recovery, execute, observation, _, _ = await prepared(payout_env)
    await execute(observation)
    with (
        pytest.raises(RuntimeError, match="repayment_history_exists"),
        payout_env["pg"].begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
