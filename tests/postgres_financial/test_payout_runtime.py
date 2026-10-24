"""Real captured successful work funds a versioned owner payout reservation."""

import asyncio
import base64
import os
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.helpers.payout_contracts import acceptance_fields, publication_fields
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    finish_work,
    process_work_events,
    start_flow,
    wallet,
)
from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    RecordPayoutResult,
    RequestPayout,
    ReviewPayout,
    StorePayoutRequisites,
)
from ugc_bot.container.payout_factory import build_payout_service
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.payout_models import TABLE_MAP

capture_env = _capture_env


@pytest_asyncio.fixture
async def payout_env(capture_env, monkeypatch):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        await finish_work(env, flow)
        await process_work_events(env, flow)
        flow["clock"].at += timedelta(days=14)
        await flow["command"](
            "advance", None, 4, system_actor="collaboration_scheduler"
        )
        await process_work_events(env, flow)
        assert wallet(env, flow["manager"])["available_minor"] == 60000
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(admin=True)
            )
        config = flow["container"]._config
        config.financial.payouts_enabled = True
        config.financial.requisites_key = SecretStr(
            base64.urlsafe_b64encode(os.urandom(32)).decode()
        )
        config.financial.requisites_key_id = "synthetic-ephemeral"
        config.financial.manual_bank_account_id = "synthetic-origin-account"
        config.financial.manual_bank_source_id = "synthetic-bank-source"
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

        async with flow["container"].transaction_manager.transaction() as db:
            old = await service.repository.latest_requirements(session=db)
        publication = PublishPayoutRequirements(
            actor_id=env["client"],
            operation_key="publish:test",
            reason=(
                "Synthetic recipient requirements fixture; "
                "not production approval"
            ),
            expected_version=old["version"] if old else 0,
            effective_from=flow["clock"].at,
            legal_reference="synthetic:legal-requirements",
            terms_reference="synthetic:payout-terms",
            evidence_reference="synthetic:reviewed-document",
            required_fields=("recipient_name", "bank_account", "legal_status"),
            **publication_fields(),
        )
        requirements = await execute(publication)
        details = {
            "recipient_name": "Synthetic Recipient",
            "bank_account": "123456789012",
            "legal_status": "synthetic-fixture",
        }
        store = StorePayoutRequisites(
            actor_id=flow["manager"],
            operation_key="details:test",
            requirements_id=requirements["requirements_id"],
            accepted_terms_reference="synthetic:payout-terms",
            details=details,
            **acceptance_fields(requirements),
        )
        requisites = await execute(store)
        yield env | dict(
            flow=flow,
            config=config,
            service=service,
            execute=execute,
            publication=publication,
            requirements=requirements,
            requisites=requisites,
            details=details,
            store=store,
        )
    finally:
        await flow["container"].dispose()


def request_command(env, **changes):
    return RequestPayout(
        **(
            dict(
                actor_id=env["flow"]["manager"],
                operation_key="request:test",
                requisites_id=env["requisites"]["requisites_id"],
                amount_minor=60000,
            )
            | changes
        )
    )


def review_command(env, state, action, **changes):
    return ReviewPayout(
        **(
            dict(
                actor_id=env["client"],
                operation_key=action
                + ":"
                + str(state["request_id"])
                + ":"
                + str(state["version"]),
                request_id=state["request_id"],
                expected_version=state["version"],
                action=action,
                reason="Actual synthetic reviewed manual transfer",
                evidence_reference="synthetic:review-evidence",
            )
            | changes
        )
    )


async def prepare(env, amount=60000, key="request:test"):
    state = await env["execute"](
        request_command(env, amount_minor=amount, operation_key=key)
    )
    state = await env["execute"](review_command(env, state, "review"))
    return await env["execute"](review_command(env, state, "start"))


def result_command(env, state, **changes):
    return RecordPayoutResult(
        **(
            dict(
                actor_id=env["client"],
                operation_key="result:" + str(uuid4()),
                request_id=state["request_id"],
                execution_id=state["execution_id"],
                fence=state["fence"],
                expected_version=state["version"],
                status="paid",
                reason="Reviewed synthetic settled statement",
                evidence_reference="synthetic:bank-statement",
                evidence_hash="a" * 64,
                bank_account="synthetic-origin-account",
                bank_reference="synthetic:" + str(uuid4()),
                amount_minor=state["amount_minor"],
                currency="RUB",
                settled_at=env["flow"]["clock"].at,
                recipient_details=env["details"],
            )
            | changes
        )
    )


def rows(env, name):
    with Session(env["pg"]) as db:
        return db.execute(select(TABLE_MAP[name])).mappings().all()


@pytest.mark.asyncio
async def test_actual_available_work_reserves_and_manual_paid_is_proven(
    payout_env,
):
    env = payout_env
    command = request_command(env)
    request = await env["execute"](command)
    assert request["state"] == "reserved" and request["amount_minor"] == 60000
    assert await env["execute"](command) == request
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 0
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    approved = await env["execute"](review_command(env, request, "review"))
    prepared = await env["execute"](review_command(env, approved, "start"))
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 0
    result = result_command(env, prepared)
    paid = await env["execute"](result)
    assert paid["state"] == "paid"
    assert await env["execute"](result) == paid
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 60000
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [59999, 0, None])
async def test_actual_mismatched_bank_fact_is_retained_unapplied(
    payout_env, amount
):
    env = payout_env
    prepared = await prepare(env)
    result = await env["execute"](
        result_command(env, prepared, amount_minor=amount)
    )
    assert result["state"] == "unknown"
    actual = [
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    ]
    assert len(actual) == 1 and actual[0]["status"] == "paid"
    assert actual[0]["amount_minor"] == amount and not actual[0]["applied"]
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 0


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_reserve_same_actual_available(
    payout_env,
):
    env = payout_env
    outcomes = await asyncio.gather(
        env["execute"](request_command(env, operation_key="one")),
        env["execute"](request_command(env, operation_key="two")),
        return_exceptions=True,
    )
    assert len([r for r in outcomes if isinstance(r, dict)]) == 1
    assert [str(r) for r in outcomes if isinstance(r, ValueError)] == [
        "payout_available_insufficient"
    ]
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_rejection_releases_allocation_without_legacy_daily_cap(
    payout_env,
):
    env = payout_env
    request = await env["execute"](request_command(env, amount_minor=30000))
    rejected = await env["execute"](review_command(env, request, "reject"))
    assert rejected["state"] == "rejected"
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 60000
    again = await env["execute"](
        request_command(env, operation_key="another_same_day")
    )
    assert again["state"] == "reserved"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "unknown"])
async def test_failed_unknown_never_release_or_automatically_restart(
    payout_env, status
):
    env = payout_env
    prepared = await prepare(env)
    result = await env["execute"](
        result_command(
            env,
            prepared,
            status=status,
            amount_minor=None,
            currency=None,
            settled_at=None,
            recipient_details={},
        )
    )
    assert result["state"] == status
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    if status == "unknown":
        with pytest.raises(ValueError, match="payout_state_not_reviewable"):
            await env["execute"](review_command(env, result, "reject"))


@pytest.mark.asyncio
async def test_stale_settled_outcome_is_retained_for_review(payout_env):
    env = payout_env
    prepared = await prepare(env)
    value = await env["execute"](
        result_command(env, prepared, expected_version=2)
    )
    assert (
        value["state"] == "unknown"
        and value["block_reason"] == "payout_stale_execution"
    )
    assert any(
        r["status"] == "paid" and not r["applied"]
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    )


@pytest.mark.asyncio
async def test_reservation_payload_conflict_and_role_demotion_are_not_replays(
    payout_env,
):
    env = payout_env
    command = request_command(env)
    request = await env["execute"](command)
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await env["execute"](replace(command, amount_minor=50000))
    await env["execute"](review_command(env, request, "review"))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(admin=False)
        )
    with pytest.raises(ValueError, match="active_admin_required"):
        await env["execute"](review_command(env, request, "review"))


@pytest.mark.asyncio
async def test_legacy_repository_cannot_read_or_mark_v1_anchor_paid(payout_env):
    from ugc_bot.domain.enums import PayoutRequestStatus
    from ugc_bot.infrastructure.db.repositories.referrals import (
        SqlAlchemyPayoutRequestRepository,
    )

    env = payout_env
    state = await env["execute"](request_command(env))
    repo = SqlAlchemyPayoutRequestRepository(
        env["flow"]["container"].session_factory
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        assert (
            await repo.get_by_id(UUID(state["request_id"]), session=db) is None
        )
        assert not await repo.update_status(
            UUID(state["request_id"]), PayoutRequestStatus.PAID, session=db
        )
        assert (
            list(await repo.list_by_user(env["flow"]["manager"], session=db))
            == []
        )
        assert (
            await repo.get_pending_totals_by_currency(
                env["flow"]["manager"], session=db
            )
            == {}
        )


@pytest.mark.asyncio
async def test_allocation_cannot_claim_another_recipient_obligation(payout_env):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.base import Base

    env = payout_env
    state = await env["execute"](request_command(env, amount_minor=30000))
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        foreign = db.scalar(
            select(obligations.c.id)
            .where(obligations.c.recipient_id == env["flow"]["partner"])
            .limit(1)
        )
    with pytest.raises(IntegrityError), Session(env["pg"]) as db, db.begin():
        db.execute(
            TABLE_MAP["allocations"]
            .insert()
            .values(
                allocation_id=uuid4(),
                request_id=state["request_id"],
                obligation_id=foreign,
                recipient_id=env["flow"]["manager"],
                amount_minor=1,
                currency="RUB",
            )
        )


@pytest.mark.asyncio
async def test_legacy_request_cannot_be_forged_into_v1_authority(payout_env):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.models import PayoutRequestModel

    env = payout_env
    ref = uuid4()
    now = env["flow"]["clock"].at
    with Session(env["pg"]) as db, db.begin():
        db.add(
            PayoutRequestModel(
                request_id=ref,
                user_id=env["flow"]["manager"],
                amount=1,
                currency="RUB",
                requested_at=now,
            )
        )
    with (
        pytest.raises(IntegrityError, match="payout_request_anchor_invalid"),
        Session(env["pg"]) as db,
        db.begin(),
    ):
        db.execute(
            TABLE_MAP["requests"]
            .insert()
            .values(
                request_id=ref,
                recipient_id=env["flow"]["manager"],
                amount_minor=100,
                currency="RUB",
                requisites_id=env["requisites"]["requisites_id"],
                requirements_id=env["requirements"]["requirements_id"],
                requested_at=now,
                deadline_at=now + timedelta(hours=72),
            )
        )


@pytest.mark.asyncio
async def test_unapplied_bank_observation_cannot_authorize_settlement(
    payout_env,
):
    from sqlalchemy.exc import IntegrityError

    env = payout_env
    prepared = await prepare(env)
    await env["execute"](result_command(env, prepared, amount_minor=59999))
    outcome = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    )
    with (
        pytest.raises(IntegrityError, match="payout_settlement_proof_invalid"),
        Session(env["pg"]) as db,
        db.begin(),
    ):
        db.execute(
            TABLE_MAP["settlements"]
            .insert()
            .values(
                execution_id=prepared["execution_id"],
                request_id=prepared["request_id"],
                outcome_id=outcome["outcome_id"],
                amount_minor=60000,
                currency="RUB",
                bank_account=outcome["bank_account"],
                bank_reference=outcome["bank_reference"],
                settled_at=outcome["settled_at"],
            )
        )


@pytest.mark.asyncio
async def test_wrong_bank_origin_observation_is_retained_not_paid(payout_env):
    env = payout_env
    prepared = await prepare(env)
    value = await env["execute"](
        result_command(env, prepared, bank_account="forged-bank-origin")
    )
    assert value["state"] == "unknown"
    assert value["block_reason"] == "payout_bank_account_mismatch"
    actual = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    )
    assert (
        actual["bank_account"] == "forged-bank-origin" and not actual["applied"]
    )


@pytest.mark.asyncio
async def test_actual_bank_fact_survives_refused_money_application(
    payout_env, monkeypatch
):
    env = payout_env
    prepared = await prepare(env)
    original = env["service"].repository.movement_locked

    async def refuse_paid(movement, *, session):
        if movement.bucket_to == "paid":
            raise ValueError("synthetic_payout_money_guard_refused")
        return await original(movement, session=session)

    monkeypatch.setattr(
        env["service"].repository, "movement_locked", refuse_paid
    )
    value = await env["execute"](result_command(env, prepared))
    assert value["state"] == "unknown"
    actual = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    )
    assert actual["status"] == "paid" and not actual["applied"]
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    assert not [
        r
        for r in rows(env, "settlements")
        if str(r["request_id"]) == prepared["request_id"]
    ]


@pytest.mark.asyncio
async def test_actual_bank_observation_is_not_lost_when_key_becomes_unavailable(
    payout_env,
):
    env = payout_env
    prepared = await prepare(env)
    env["service"].crypto = None
    value = await env["execute"](result_command(env, prepared))
    assert value["state"] == "unknown"
    assert value["block_reason"] == "payout_encryption_configuration_required"
    outcome = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == prepared["request_id"]
    )
    assert outcome["status"] == "paid" and not outcome["applied"]
    assert not outcome["ciphertext"] and outcome["key_id"] == "unavailable"
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_stopping_payouts_does_not_discard_inflight_actual_bank_fact(
    payout_env,
):
    env = payout_env
    prepared = await prepare(env)
    env["config"].financial.payouts_enabled = False
    value = await env["execute"](result_command(env, prepared))
    assert (
        value["state"] == "unknown"
        and value["block_reason"] == "financial_payouts_disabled"
    )
    assert any(
        str(r["request_id"]) == prepared["request_id"]
        and r["status"] == "paid"
        and not r["applied"]
        for r in rows(env, "outcomes")
    )
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_unmatched_actual_bank_settlement_blocks_new_recipient_payout(
    payout_env,
):
    env = payout_env
    prepared = await prepare(env, 30000)
    await env["execute"](result_command(env, prepared, amount_minor=29999))
    with pytest.raises(ValueError, match="payout_bank_reconciliation_required"):
        await env["execute"](
            request_command(
                env, amount_minor=30000, operation_key="next-reserve"
            )
        )


@pytest.mark.asyncio
async def test_current_version_resolves_same_physical_stale_observation(
    payout_env,
):
    env = payout_env
    prepared = await prepare(env)
    command = result_command(env, prepared, expected_version=2)
    unknown = await env["execute"](command)
    assert unknown["state"] == "unknown"
    paid = await env["execute"](
        replace(
            command,
            expected_version=unknown["version"],
            operation_key="reviewed-same-bank-proof",
        )
    )
    assert paid["state"] == "paid"
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 60000


@pytest.mark.asyncio
async def test_public_requirements_hide_admin_approval_evidence(payout_env):
    env = payout_env
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        value = await env["service"].requirements_for_actor(
            env["flow"]["manager"], session=db
        )
    assert value["terms_reference"] == "synthetic:payout-terms"
    assert not {
        "actor_id",
        "legal_reference",
        "evidence_reference",
        "reason",
    } & set(value)


@pytest.mark.asyncio
async def test_prepared_intent_cannot_change_frozen_request_amount(payout_env):
    from sqlalchemy.exc import IntegrityError

    env = payout_env
    state = await prepare(env)
    ref = UUID(state["request_id"])
    actual = next(r for r in rows(env, "intents") if r["request_id"] == ref)
    forged = {key: value for key, value in actual.items()}
    forged.update(execution_id=uuid4(), fence=uuid4(), amount_minor=1)
    with pytest.raises(IntegrityError), Session(env["pg"]) as db, db.begin():
        db.execute(TABLE_MAP["intents"].insert().values(**forged))


@pytest.mark.asyncio
async def test_recipient_block_after_reserve_prevents_execution(payout_env):
    env = payout_env
    state = await env["execute"](request_command(env))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["flow"]["manager"])
            .values(status="blocked")
        )
    value = await env["execute"](review_command(env, state, "review"))
    assert (
        value["state"] == "blocked"
        and value["block_reason"] == "active_actor_required"
    )
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_admin_can_reject_unstarted_reserve_after_requirements_change(
    payout_env,
):
    env = payout_env
    state = await env["execute"](request_command(env))
    await env["execute"](
        replace(
            env["publication"],
            operation_key="new-policy",
            expected_version=env["requirements"]["version"],
            terms_reference="synthetic:changed-terms",
        )
    )
    result = await env["execute"](review_command(env, state, "reject"))
    assert result["state"] == "rejected"
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 60000


@pytest.mark.asyncio
async def test_72_hour_escalation_is_due_once_and_never_pays(payout_env):
    env = payout_env
    state = await env["execute"](request_command(env))
    at = env["flow"]["clock"].at
    env["flow"]["clock"].at = (
        at + timedelta(hours=72) - timedelta(microseconds=1)
    )
    with pytest.raises(ValueError, match="payout_sla_not_overdue"):
        await env["execute"](review_command(env, state, "escalate"))
    env["flow"]["clock"].at = at + timedelta(hours=72)
    escalated = await env["execute"](review_command(env, state, "escalate"))
    again = await env["execute"](
        review_command(
            env, escalated, "escalate", operation_key="another-overdue-scan"
        )
    )
    events = [
        r
        for r in rows(env, "events")
        if str(r["request_id"]) == state["request_id"]
        and r["action"] == "escalate"
    ]
    assert len(events) == 1 and again == escalated
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 0


@pytest.mark.asyncio
async def test_concurrent_same_operation_reserves_exactly_once(payout_env):
    env = payout_env
    values = await asyncio.gather(
        env["execute"](request_command(env)),
        env["execute"](request_command(env)),
    )
    assert values[0] == values[1]
    assert (
        len(
            [
                r
                for r in rows(env, "requests")
                if r["recipient_id"] == env["flow"]["manager"]
            ]
        )
        == 1
    )
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_one_actual_bank_reference_cannot_pay_two_reserved_requests(
    payout_env,
):
    env = payout_env
    first = await prepare(env, 30000, "first-half")
    second = await prepare(env, 30000, "second-half")
    reference = "same-actual-transfer:" + str(uuid4())
    results = await asyncio.gather(
        env["execute"](result_command(env, first, bank_reference=reference)),
        env["execute"](result_command(env, second, bank_reference=reference)),
    )
    assert sorted(r["state"] for r in results) == ["paid", "unknown"]
    actual = [
        r for r in rows(env, "outcomes") if r["bank_reference"] == reference
    ]
    assert len(actual) == 2 and sum(r["applied"] for r in actual) == 1
    value = wallet(env, env["flow"]["manager"])
    assert value["paid_minor"] == 30000 and value["reserved_minor"] == 30000


@pytest.mark.asyncio
async def test_reservation_and_audit_failure_roll_back_all_money(
    payout_env, monkeypatch
):
    env = payout_env
    repository = env["service"].repository
    original = repository.add

    async def fail(name, values, *, session):
        await original(name, values, session=session)
        if name == "commands" and values["action"] == "RequestPayout":
            raise RuntimeError("synthetic_after_payout_command")

    monkeypatch.setattr(repository, "add", fail)
    with pytest.raises(RuntimeError, match="synthetic_after_payout_command"):
        await env["execute"](request_command(env))
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 60000
    assert not [
        r
        for r in rows(env, "requests")
        if r["recipient_id"] == env["flow"]["manager"]
    ]
    monkeypatch.setattr(repository, "add", original)
    assert (await env["execute"](request_command(env)))["state"] == "reserved"


@pytest.mark.asyncio
async def test_actual_sql_application_refusal_preserves_observed_bank_fact(
    payout_env, monkeypatch
):
    env = payout_env
    state = await prepare(env)
    repository = env["service"].repository
    original = repository.add

    async def duplicate(name, values, *, session):
        await original(name, values, session=session)
        if name == "settlements":
            await original(name, values, session=session)

    monkeypatch.setattr(repository, "add", duplicate)
    value = await env["execute"](result_command(env, state))
    assert value["state"] == "unknown"
    actual = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == state["request_id"]
    )
    assert actual["status"] == "paid" and not actual["applied"]
    assert not [
        r
        for r in rows(env, "settlements")
        if str(r["request_id"]) == state["request_id"]
    ]
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_missing_origin_configuration_never_starts_manual_execution(
    payout_env,
):
    env = payout_env
    state = await env["execute"](request_command(env))
    state = await env["execute"](review_command(env, state, "review"))
    env["config"].financial.manual_bank_account_id = ""
    with pytest.raises(
        ValueError, match="payout_bank_account_configuration_required"
    ):
        await env["execute"](review_command(env, state, "start"))
    assert not [
        r
        for r in rows(env, "intents")
        if str(r["request_id"]) == state["request_id"]
    ]
    env["config"].financial.manual_bank_account_id = "synthetic-origin-account"
    assert (await env["execute"](review_command(env, state, "start")))[
        "state"
    ] == "executing"


@pytest.mark.asyncio
async def test_payout_facts_and_v1_anchor_cannot_be_mutated_or_deleted(
    payout_env,
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    env = payout_env
    state = await prepare(env)
    await env["execute"](result_command(env, state))
    for name, table in TABLE_MAP.items():
        if name == "states":
            continue
        primary = list(table.primary_key.columns)[0].name
        for statement in (
            f"UPDATE {table.name} SET {primary}={primary}",
            f"DELETE FROM {table.name}",
            f"TRUNCATE {table.name} CASCADE",
        ):
            with (
                pytest.raises(
                    IntegrityError,
                    match="payout_fact_immutable|financial_ledger_immutable",
                ),
                Session(env["pg"]) as db,
                db.begin(),
            ):
                db.execute(text(statement))
    for statement in (
        "UPDATE payout_requests SET amount=amount WHERE request_id=:request",
        "DELETE FROM payout_requests WHERE request_id=:request",
    ):
        with (
            pytest.raises(IntegrityError, match="payout_anchor_immutable"),
            Session(env["pg"]) as db,
            db.begin(),
        ):
            db.execute(text(statement), {"request": state["request_id"]})
    with pytest.raises(IntegrityError), Session(env["pg"]) as db, db.begin():
        db.execute(
            text("DELETE FROM users WHERE user_id=:recipient"),
            {"recipient": env["flow"]["manager"]},
        )
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 60000


@pytest.mark.asyncio
async def test_populated_payout_revision_refuses_downgrade_before_ddl(
    payout_env,
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_payout_v1,
    )

    env = payout_env
    with (
        pytest.raises(RuntimeError, match="Cannot discard payout history"),
        env["pg"].begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        financial_payout_v1.downgrade()
    assert rows(env, "requirements")


@pytest.mark.asyncio
async def test_nil_stale_fence_retains_actual_bank_observation(payout_env):
    env = payout_env
    state = await prepare(env)
    result = await env["execute"](result_command(env, state, fence=UUID(int=0)))
    assert result["state"] == "unknown"
    assert result["block_reason"] == "payout_stale_execution"
    outcome = next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == state["request_id"]
    )
    assert outcome["status"] == "paid" and not outcome["applied"]
    assert outcome["bank_reference"]
    value = wallet(env, env["flow"]["manager"])
    assert value["reserved_minor"] == 60000 and value["paid_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [10_000_000_000, 2**63 - 1])
async def test_v1_identity_anchor_supports_bigint_authority_without_decimal(
    payout_env, amount
):
    """SQL bigint boundary only; this creates no spendable funds."""
    from ugc_bot.infrastructure.db.models import PayoutRequestModel

    env, ref = payout_env, uuid4()
    repo, flow = env["service"].repository, env["flow"]
    at = flow["clock"].at
    async with env["factory"]() as db:
        await db.begin()
        try:
            await repo.anchor(ref, flow["manager"], amount, at, session=db)
            await repo.add(
                "requests",
                dict(
                    request_id=ref,
                    recipient_id=flow["manager"],
                    amount_minor=amount,
                    currency="RUB",
                    requisites_id=env["requisites"]["requisites_id"],
                    requirements_id=env["requirements"]["requirements_id"],
                    requested_at=at,
                    deadline_at=at + timedelta(hours=72),
                ),
                session=db,
            )
            anchor = await db.get(PayoutRequestModel, ref)
            assert anchor.amount is None
            assert anchor.payout_protocol == "financial_v1"
            stored = await repo.get("requests", ref, session=db)
            assert stored["amount_minor"] == amount
        finally:
            # Boundary-only records intentionally have no reserve/state.
            # Roll back this synthetic scope; never pollute the shared schema.
            await db.rollback()
    value = wallet(env, flow["manager"])
    assert value["available_minor"] == 60000 and value["reserved_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("item_state", ["cancelled", "refunded"])
async def test_current_item_correction_blocks_before_delayed_ledger_worker(
    payout_env, item_state
):
    from ugc_bot.infrastructure.db.models import OrderItemModel

    env = payout_env
    item = env["flow"]["item"]
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderItemModel)
            .where(OrderItemModel.paid_item_id == item)
            .values(selection_state=item_state)
        )
    with pytest.raises(
        ValueError, match="payout_item_corrected_review_required"
    ):
        await env["execute"](request_command(env))
    value = wallet(env, env["flow"]["manager"])
    assert value["available_minor"] == 60000 and value["reserved_minor"] == 0


@pytest.mark.asyncio
async def test_existing_case_debt_blocks_reserve_without_offset(payout_env):
    """Synthetic persisted debt boundary; Task6c owns its real case producer."""
    from dataclasses import asdict

    from ugc_bot.application.financial_ports import JournalMovement
    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        payload_hash,
    )

    env = payout_env
    state = await prepare(env, 30000)
    assert (
        await env["execute"](result_command(env, state, amount_minor=30000))
    )["state"] == "paid"
    movements = Base.metadata.tables["financial_movements"]
    wallets = Base.metadata.tables["financial_wallets"]
    with Session(env["pg"]) as db, db.begin():
        paid = (
            db.execute(
                select(movements).where(
                    movements.c.request_id == state["request_id"],
                    movements.c.bucket_to == "paid",
                )
            )
            .mappings()
            .one()
        )
        movement = JournalMovement(
            obligation_id=paid["obligation_id"],
            operation_key="synthetic:existing-case-debt:" + str(uuid4()),
            event_id="synthetic:case-debt-boundary",
            movement_type="debt",
            amount_minor=5000,
            currency="RUB",
            effective_at=env["flow"]["clock"].at,
            recorded_at=env["flow"]["clock"].at,
            actor_id=env["client"],
            actor_kind="admin",
            reason="Synthetic historical case debt boundary",
            source_entry_id=paid["id"],
            case_id=uuid4(),
        )
        values = asdict(movement)
        db.execute(
            movements.insert().values(
                **values, id=uuid4(), payload_hash=payload_hash(values)
            )
        )
        db.execute(
            update(wallets)
            .where(wallets.c.recipient_id == env["flow"]["manager"])
            .values(
                debt_minor=wallets.c.debt_minor + 5000,
                cancelled_minor=wallets.c.cancelled_minor + 5000,
                version=wallets.c.version + 1,
            )
        )
    with pytest.raises(ValueError, match="payout_debt_manual_review_required"):
        await env["execute"](
            request_command(env, operation_key="after-debt", amount_minor=10000)
        )
    value = wallet(env, env["flow"]["manager"])
    assert value["available_minor"] == 30000 and value["reserved_minor"] == 0
    assert value["paid_minor"] == 30000 and value["debt_minor"] == 5000


@pytest.mark.asyncio
async def test_unapplied_bank_reference_cannot_pay_a_different_recipient(
    payout_env, user_repo, advertiser_repo, monkeypatch
):
    from contextlib import asynccontextmanager

    env = payout_env
    first = await prepare(env)
    reference = "synthetic-physical-reference:" + str(uuid4())
    observed = await env["execute"](
        result_command(
            env,
            first,
            expected_version=first["version"] + 1,
            bank_reference=reference,
        )
    )
    assert observed["state"] == "unknown"
    assert not next(
        r
        for r in rows(env, "outcomes")
        if str(r["request_id"]) == first["request_id"]
    )["applied"]
    async with (
        asynccontextmanager(capture_env.__wrapped__)(
            env["pg"], user_repo, advertiser_repo
        ) as second_capture,
        asynccontextmanager(globals()["payout_env"].__wrapped__)(
            second_capture, monkeypatch
        ) as other,
    ):
        assert other["flow"]["manager"] != env["flow"]["manager"]
        second = await prepare(other)
        result = await other["execute"](
            result_command(other, second, bank_reference=reference)
        )
        assert result["state"] == "unknown"
        assert result["block_reason"] == "payout_bank_reference_reused"
        facts = [
            r
            for r in rows(other, "outcomes")
            if str(r["request_id"]) == second["request_id"]
        ]
        assert len(facts) == 1 and not facts[0]["applied"]
        balance = wallet(other, other["flow"]["manager"])
        assert balance["reserved_minor"] == 60000
        assert balance["paid_minor"] == 0


@pytest.mark.asyncio
async def test_legacy_lists_and_totals_preserve_actual_legacy_rows_only(
    payout_env,
):
    from datetime import datetime, timezone
    from decimal import Decimal

    from ugc_bot.infrastructure.db.models import PayoutRequestModel
    from ugc_bot.infrastructure.db.repositories.referrals import (
        SqlAlchemyPayoutRequestRepository,
    )

    env = payout_env
    state = await env["execute"](request_command(env))
    legacy_id, manager = uuid4(), env["flow"]["manager"]
    with Session(env["pg"]) as db, db.begin():
        db.add(
            PayoutRequestModel(
                request_id=legacy_id,
                user_id=manager,
                requested_at=datetime.now(timezone.utc),
                amount=Decimal("123.45"),
                currency="RUB",
                status="pending",
            )
        )
    repo = SqlAlchemyPayoutRequestRepository(
        env["flow"]["container"].session_factory
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        old = await repo.get_by_id(legacy_id, session=db)
        assert old.request_id == legacy_id and old.amount == Decimal("123.45")
        assert (
            await repo.get_by_id(UUID(state["request_id"]), session=db) is None
        )
        assert {
            r.request_id for r in await repo.list_by_user(manager, session=db)
        } == {legacy_id}
        assert {
            r.request_id
            for r in await repo.list_by_user_ids([manager], session=db)
        } == {legacy_id}
        assert await repo.get_pending_totals_by_currency(
            manager, session=db
        ) == {"RUB": Decimal("123.45")}
        assert await repo.get_paid_totals_by_currency(manager, session=db) == {}
        assert await repo.has_request_today_by_currency(
            manager, session=db
        ) == {"RUB": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["approved", "version", "block"])
async def test_mutable_request_projection_cannot_authorize_admin_mutation(
    payout_env, corruption
):
    env = payout_env
    state = await env["execute"](request_command(env))
    table = TABLE_MAP["states"]
    ref = UUID(state["request_id"])
    original = next(r for r in rows(env, "states") if r["request_id"] == ref)
    changes = {
        "approved": {"state": "approved"},
        "version": {"version": original["version"] + 50},
        "block": {"block_reason": "forged_manual_review_flag"},
    }[corruption]
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(table).where(table.c.request_id == ref).values(**changes)
        )
    try:
        action = "start" if corruption == "approved" else "review"
        command = review_command(
            env,
            state,
            action,
            expected_version=changes.get("version", state["version"]),
        )
        with pytest.raises(
            ValueError, match="payout_state_reconciliation_required"
        ):
            await env["execute"](command)
        async with env["flow"][
            "container"
        ].transaction_manager.transaction() as db:
            with pytest.raises(
                ValueError, match="payout_state_reconciliation_required"
            ):
                await env["service"].get_for_actor(
                    ref, env["flow"]["manager"], session=db
                )
        assert (
            len([r for r in rows(env, "events") if r["request_id"] == ref]) == 1
        )
        assert not [r for r in rows(env, "intents") if r["request_id"] == ref]
        assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000
    finally:
        # Restore only the explicitly corrupted mutable test projection.
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(table)
                .where(table.c.request_id == ref)
                .values(**dict(original))
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["execution", "version"])
async def test_bank_fact_survives_bad_projection_then_explicit_resolution(
    payout_env, corruption
):
    env = payout_env
    state = await prepare(env)
    ref, table = UUID(state["request_id"]), TABLE_MAP["states"]
    original = next(r for r in rows(env, "states") if r["request_id"] == ref)
    changes = (
        {"execution_id": None} if corruption == "execution" else {"version": 99}
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(table).where(table.c.request_id == ref).values(**changes)
        )
    command = result_command(env, state)
    event_ids = {
        r["event_id"] for r in rows(env, "events") if r["request_id"] == ref
    }
    try:
        result = await env["execute"](command)
        assert result["state"] == "unavailable"
        assert result["block_reason"] == "payout_state_reconciliation_required"
        assert not result["applied"]
        assert await env["execute"](command) == result
        outcomes = [r for r in rows(env, "outcomes") if r["request_id"] == ref]
        assert len(outcomes) == 1 and not outcomes[0]["applied"]
        assert outcomes[0]["bank_reference"] == command.bank_reference
        assert {
            r["event_id"] for r in rows(env, "events") if r["request_id"] == ref
        } == event_ids
        current = next(r for r in rows(env, "states") if r["request_id"] == ref)
        assert all(current[k] == v for k, v in changes.items())
        assert wallet(env, env["flow"]["manager"])["paid_minor"] == 0
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(table)
                .where(table.c.request_id == ref)
                .values(**dict(original))
            )
    resolved = await env["execute"](
        replace(
            command,
            operation_key="explicit-projection-resolved:" + str(uuid4()),
        )
    )
    assert resolved["state"] == "paid"
    assert wallet(env, env["flow"]["manager"])["paid_minor"] == 60000
    facts = [r for r in rows(env, "outcomes") if r["request_id"] == ref]
    assert len(facts) == 2 and sum(r["applied"] for r in facts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "array", "execution"])
async def test_incomplete_immutable_state_proof_is_unavailable_not_inferred(
    payout_env, invalid
):
    from ugc_bot.application.collaboration_ports import canonical

    env = payout_env
    state = await prepare(env)
    ref, repo = UUID(state["request_id"]), env["service"].repository
    table = TABLE_MAP["states"]
    async with env["factory"]() as db:
        await db.begin()
        try:
            original = await repo.get("states", ref, session=db)
            proof = canonical(
                dict(original) | {"version": original["version"] + 1}
            )
            if invalid == "execution":
                proof["execution_id"] = "invalid-persisted-pointer"
            details = {} if invalid == "missing" else {"projection": proof}
            if invalid == "array":
                details = ["older-incomplete-shape"]
            await repo.add(
                "events",
                dict(
                    event_id=uuid4(),
                    request_id=ref,
                    version=proof["version"],
                    state=original["state"],
                    actor_id=env["client"],
                    action="synthetic_invalid_audit_boundary",
                    reason="Synthetic incomplete immutable history boundary",
                    recorded_at=env["flow"]["clock"].at,
                    details=details,
                ),
                session=db,
            )
            await db.execute(
                update(table)
                .where(table.c.request_id == ref)
                .values(version=proof["version"])
            )
            with pytest.raises(
                ValueError, match="payout_state_reconciliation_required"
            ):
                await repo.view(ref, session=db)
            with pytest.raises(
                ValueError, match="payout_state_reconciliation_required"
            ):
                await repo.transition(
                    ref,
                    "paid",
                    env["client"],
                    "synthetic",
                    "Must fail closed",
                    env["flow"]["clock"].at,
                    session=db,
                )
            observed = await env["service"].execute(
                result_command(env, state), session=db
            )
            assert (
                observed["state"] == "unavailable"
                and observed["version"] is None
            )
            assert not observed["applied"]
        finally:
            # This synthetic audit-shape fault is confined to a rollback.
            await db.rollback()
