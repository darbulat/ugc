"""Current-head actual correction commands; no refund monetary application."""

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.helpers.correction_runtime_pg import (
    authority_race,
    corrupt_case,
    pending_runtime,
    runtime,
)
from tests.postgres_financial.test_order_intake import intake_env as intake_env

__all__ = ["intake_env"]


@pytest_asyncio.fixture
async def correction_env(intake_env):
    yield await runtime(intake_env)


@pytest.fixture(scope="session")
def correction_evidence():
    records = []
    yield records
    path = os.environ.get("CORRECTION_TASK4_EVIDENCE_PATH")
    if path:
        Path(path).write_text(json.dumps(records, indent=2) + "\n")


@pytest.mark.asyncio
async def test_actual_captured_writer_retains_genuine_approval_proof_and_match(
    correction_env,
):
    rt = correction_env
    with Session(rt.env["pg"]) as db:
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            == ScriptDirectory.from_config(
                Config("alembic.ini")
            ).get_current_head()
        )
    requested = await rt.execute(await rt.request())
    approved = await rt.execute(rt.review(requested))
    observed = await rt.execute(rt.observation(approved))
    matched = await rt.execute(rt.match(observed, approved, observed))
    assert matched["application_status"] == "awaiting_assessment"
    assert matched["applied"] is False
    intent = rt.rows("intents", intent_id=UUID(approved["intent_id"]))[0]
    event = rt.rows("events", case_id=UUID(approved["case_id"]), version=2)[0]
    from tests.helpers.correction_approval_pg import ApprovalRuntime

    approval = ApprovalRuntime.from_runtime(rt).approval_rows(
        "approvals", approval_id=UUID(approved["approval_id"])
    )[0]
    command = rt.rows("commands", command_id=approval["command_id"])[0]
    assert command["action"] == "ReviewSelectionRefund"
    assert event["actor_id"] == rt.env["admin"].user_id
    assert event["command_id"] == command["command_id"]
    assert event["source_id"] == approval["approval_id"]
    assert approval["intent_id"] == intent["intent_id"]
    assert approval["capture_id"] != rt.facts["invoice_id"]
    assert intent["capture_id"] is None
    assert matched["approval_id"] == approved["approval_id"]
    assert ApprovalRuntime.from_runtime(rt).approval_rows(
        "match_approvals", match_id=UUID(matched["match_id"])
    ) == [
        {
            "match_id": UUID(matched["match_id"]),
            "approval_id": approval["approval_id"],
        }
    ]
    claim = rt.claims(approved["intent_id"])[0]
    assert claim["producer"] == "refund"
    assert claim["observation_id"] == UUID(observed["observation_id"])
    assert not rt.rows("applications", intent_id=intent["intent_id"])


@pytest.mark.asyncio
async def test_actual_replay_separates_old_receipt_and_private_fresh_state(
    correction_env,
):
    rt = correction_env
    command = await rt.request()
    requested = await rt.execute(command)
    approved = await rt.execute(rt.review(requested))
    observed = await rt.execute(rt.observation(approved))
    assert await rt.execute(command) == requested
    tm = rt.env["container"].transaction_manager
    async with tm.transaction() as db:
        own = await rt.service.get_for_actor(
            UUID(requested["case_id"]),
            command.actor_id,
            session=db,
            principal=rt.principal(command.actor_id),
        )
    async with tm.transaction() as db:
        operation = await rt.service.operation_for_actor(
            command.actor_id,
            command.operation_key,
            session=db,
            principal=rt.principal(command.actor_id),
        )
    assert own["current"]["version"] == observed["version"]
    assert "observations" not in own
    assert "synthetic-correction-account" not in str(own)
    assert operation["original_result"] == requested
    assert operation["current"]["version"] == observed["version"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "case", "operation"])
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("first", ["writer", "reader"])
@pytest.mark.parametrize(
    "change", ["native", "status", "admin", "owner", "source"]
)
async def test_actual_authority_fences_and_source_denial_order(
    correction_env, correction_evidence, entry, platform, first, change
):
    record = await authority_race(
        correction_env,
        entry=entry,
        platform=platform,
        change=change,
        first=first,
    )
    correction_evidence.append(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["case", "operation"])
@pytest.mark.parametrize(
    "field,nullable",
    [
        ("client_id", False),
        ("order_id", False),
        ("client_id", True),
        ("order_id", True),
    ],
)
async def test_actual_nonnull_bindings_refuse_and_early_nulls_remain(
    correction_env, entry, field, nullable
):
    rt = correction_env
    command = await rt.request()
    own = await rt.execute(command)
    case_id = UUID(own["case_id"])
    value = None if nullable else rt.facts["stranger"]
    if field == "order_id" and not nullable:
        from tests.postgres_financial.test_order_intake import (
            command as intake_command,
        )
        from tests.postgres_financial.test_order_intake import service

        other = await service(rt.env).create(intake_command(rt.env))
        value = other.order_id
    with corrupt_case(rt, case_id, **{field: value}):
        async with rt.env["container"].transaction_manager.transaction() as db:

            async def call():
                if entry == "case":
                    return await rt.service.get_for_actor(
                        case_id,
                        command.actor_id,
                        session=db,
                        principal=rt.principal(command.actor_id),
                    )
                return await rt.service.operation_for_actor(
                    command.actor_id,
                    command.operation_key,
                    session=db,
                    principal=rt.principal(command.actor_id),
                )

            if nullable:
                assert (await call())["state_unavailable"] is False
            else:
                with pytest.raises(
                    ValueError, match="correction_case_scope_invalid"
                ):
                    await call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["version", "source", "amount", "currency", "component", "proof"]
)
async def test_actual_refusals_retain_observation_and_original_owner(
    correction_env, case
):
    rt = correction_env
    approved = await rt.approved()
    changes = {
        "amount": {"amount_minor": 249999},
        "currency": {"currency": "USD"},
        "component": {"reported_component": "management"},
    }.get(case, {})
    observed = await rt.execute(rt.observation(approved, **changes))
    command = rt.match(observed, approved, observed)
    if case == "version":
        command = replace(command, expected_version=1)
    elif case == "source":
        command = replace(command, expected_source_hash="f" * 64)
    elif case == "proof":
        rt.service.physical_proofs = type(rt.proofs)("", "", rt.env["clock"])
    before = rt.rows("observations", case_id=UUID(observed["case_id"]))
    owner = rt.claims(approved["intent_id"])
    with pytest.raises(ValueError):
        await rt.execute(command)
    assert rt.rows("observations", case_id=UUID(observed["case_id"])) == before
    assert rt.claims(approved["intent_id"]) == owner
    assert not rt.rows("matches", intent_id=UUID(approved["intent_id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("outer_failure", [False, True])
async def test_actual_caller_transaction_retains_expected_and_rolls_back_outer(
    correction_env, outer_failure
):
    rt = correction_env
    approved = await rt.approved()
    intent_id, case_id = UUID(approved["intent_id"]), UUID(approved["case_id"])
    before = rt.rows("events", case_id=case_id)
    observation = rt.observation(approved)

    async def work():
        async with rt.env["container"].transaction_manager.transaction() as db:
            observed = await rt.execute(observation, session=db)
            command = rt.match(observed, approved, observed)
            if outer_failure:
                matched = await rt.execute(command, session=db)
                assert matched["application_status"] == "awaiting_assessment"
                raise RuntimeError("declared synthetic caller rollback")
            with pytest.raises(ValueError, match="correction_source_conflict"):
                await rt.execute(
                    replace(command, expected_source_hash="f" * 64), session=db
                )

    if outer_failure:
        with pytest.raises(RuntimeError, match="caller rollback"):
            await work()
        assert rt.rows("events", case_id=case_id) == before
        assert not rt.rows("observations", intent_id=intent_id)
        assert not rt.claims(approved["intent_id"])
    else:
        await work()
        assert len(rt.rows("observations", intent_id=intent_id)) == 1
        assert len(rt.claims(approved["intent_id"])) == 1
    assert not rt.rows("matches", intent_id=intent_id)
    assert not rt.rows("applications", intent_id=intent_id)


@pytest.mark.asyncio
async def test_actual_early_invoice_observation_keeps_intent_and_adds_approval(
    intake_env,
):
    from tests.helpers.corrections import captured_order

    rt = await pending_runtime(intake_env)
    command = rt.observation(
        original_payment_reference="provider-" + str(rt.facts["order"].order_id)
    )
    early = await rt.execute(command)
    intent_id = UUID(early["intent_id"])
    before = rt.rows("observations", intent_id=intent_id)
    intent = rt.rows("intents", intent_id=intent_id)
    claims = rt.claims(early["intent_id"])
    assert intent[0]["capture_id"] is None and intent[0]["request_id"] is None
    actual = await captured_order(
        rt.env, existing=(rt.facts["request"], rt.facts["order"])
    )
    actual["invoice_id"] = rt.facts["invoice_id"]
    rt.facts = actual
    requested = await rt.execute(
        await rt.request(existing_case_id=UUID(early["case_id"]))
    )
    approved = await rt.execute(rt.review(requested))
    matched = await rt.execute(rt.match(approved, approved, early))
    assert approved["intent_id"] == early["intent_id"]
    assert matched["approval_id"] == approved["approval_id"]
    assert matched["application_status"] == "awaiting_assessment"
    assert rt.rows("observations", intent_id=intent_id) == before
    assert rt.rows("intents", intent_id=intent_id) == intent
    assert rt.claims(early["intent_id"]) == claims
    assert len(rt.rows("matches", intent_id=intent_id)) == 1
    assert not rt.rows("applications", intent_id=intent_id)


@pytest.mark.asyncio
async def test_actual_same_intent_new_report_and_fresh_matches_preserve_owner(
    correction_env,
):
    rt = correction_env
    approved = await rt.approved()
    command = rt.observation(approved)
    first = await rt.execute(command)
    owner = rt.claims(approved["intent_id"])
    second = await rt.execute(
        rt.observation(first, bank_reference=command.bank_reference)
    )
    matched = await rt.execute(rt.match(second, approved, second))
    repeated = await rt.execute(rt.match(matched, approved, second))
    assert repeated["application_status"] == "awaiting_assessment"
    assert rt.claims(approved["intent_id"]) == owner
    matches = rt.rows("matches", intent_id=UUID(approved["intent_id"]))
    assert len(matches) == 2
    assert {row["review_version"] for row in matches} == {approved["version"]}
