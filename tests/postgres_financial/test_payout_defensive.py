"""Actual owed funds remain untouched for invalid or unauthorised commands."""

from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

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
from tests.postgres_financial.test_work_entitlement_runtime import wallet
from ugc_bot.domain.financial import MAX_MINOR
from ugc_bot.infrastructure.db.models import UserModel

__all__ = ["capture_env", "payout_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,code",
    [
        ("zero", "payout_amount_invalid"),
        ("negative", "payout_amount_invalid"),
        ("bool", "payout_amount_invalid"),
        ("overflow", "payout_amount_invalid"),
        ("currency", "payout_amount_invalid"),
        ("insufficient", "payout_available_insufficient"),
        ("stranger", "payout_own_requisites_required"),
        ("missing_details", "payout_own_requisites_required"),
        ("nil_actor", "payout_identity_invalid"),
        ("bad_actor", "payout_identity_invalid"),
        ("blank_key", "payout_operation_key_required"),
        ("blocked_actor", "active_actor_required"),
        ("core_off", "financial_payouts_disabled"),
        ("payouts_off", "financial_payouts_disabled"),
        ("missing_key", "payout_encryption_configuration_required"),
    ],
)
async def test_invalid_owner_command_never_reserves_actual_funds(
    payout_env, case, code
):
    env = payout_env
    changes = {
        "zero": {"amount_minor": 0},
        "negative": {"amount_minor": -1},
        "bool": {"amount_minor": True},
        "overflow": {"amount_minor": MAX_MINOR + 1},
        "currency": {"currency": "USD"},
        "insufficient": {"amount_minor": 60001},
        "stranger": {"actor_id": env["flow"]["creator"]},
        "missing_details": {"requisites_id": uuid4()},
        "nil_actor": {"actor_id": UUID(int=0)},
        "bad_actor": {"actor_id": "not-an-id"},
        "blank_key": {"operation_key": " "},
    }.get(case, {})
    if case == "blocked_actor":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["flow"]["manager"])
                .values(status="blocked")
            )
    if case == "core_off":
        env["config"].financial.core_enabled = False
    if case == "payouts_off":
        env["config"].financial.payouts_enabled = False
    if case == "missing_key":
        env["service"].crypto = None
    with pytest.raises(ValueError, match=code):
        await env["execute"](request_command(env, **changes))
    value = wallet(env, env["flow"]["manager"])
    assert value["available_minor"] == 60000 and value["reserved_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,code",
    [
        ("nonadmin", "active_admin_required"),
        ("stale_version", "payout_version_conflict"),
        ("backdated", "payout_requirements_invalid"),
        ("duplicate_fields", "payout_requirements_invalid"),
        ("missing_fields", "payout_requirements_invalid"),
        ("invalid_field", "payout_requirements_invalid"),
        ("invalid_enabled", "payout_requirements_invalid"),
        ("reason", "payout_reason_required"),
        ("legal_reference", "payout_legal_reference_required"),
        ("terms_reference", "payout_terms_reference_required"),
        ("evidence_reference", "payout_evidence_reference_required"),
    ],
)
async def test_requirements_need_current_admin_and_actual_provenance(
    payout_env, case, code
):
    env = payout_env
    changes = {
        "nonadmin": {"actor_id": env["flow"]["manager"]},
        "stale_version": {"expected_version": 0},
        "backdated": {
            "effective_from": env["flow"]["clock"].at
            - timedelta(microseconds=1)
        },
        "duplicate_fields": {
            "required_fields": (
                "recipient_name",
                "bank_account",
                "legal_status",
                "bank_account",
            )
        },
        "missing_fields": {"required_fields": ("recipient_name",)},
        "invalid_field": {
            "required_fields": (
                "recipient_name",
                "bank_account",
                "legal_status",
                "bad field",
            )
        },
        "invalid_enabled": {"enabled": 1},
        "reason": {"reason": " "},
        "legal_reference": {"legal_reference": " "},
        "terms_reference": {"terms_reference": " "},
        "evidence_reference": {"evidence_reference": " "},
    }[case]
    command = replace(
        env["publication"],
        operation_key="invalid:" + case,
        expected_version=env["requirements"]["version"],
        **({k: v for k, v in changes.items() if k != "expected_version"}),
    )
    if "expected_version" in changes:
        command = replace(command, expected_version=changes["expected_version"])
    with pytest.raises(ValueError, match=code):
        await env["execute"](command)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,code",
    [
        ("terms", "payout_accepted_terms_and_fields_required"),
        ("fields", "payout_accepted_terms_and_fields_required"),
        ("policy", "payout_requirements_changed"),
        ("empty_value", "payout_requisites_fields_invalid"),
    ],
)
async def test_details_require_current_owner_accepted_terms_and_required_fields(
    payout_env, case, code
):
    env = payout_env
    changes = {
        "terms": {"accepted_terms_reference": "other"},
        "fields": {
            "details": {"recipient_name": "Name", "bank_account": "123"}
        },
        "policy": {"requirements_id": uuid4()},
        "empty_value": {"details": env["details"] | {"bank_account": ""}},
    }[case]
    with pytest.raises(ValueError, match=code):
        await env["execute"](
            replace(
                env["store"], operation_key="invalid-details:" + case, **changes
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,code",
    [
        ("start_unapproved", "payout_review_approval_required"),
        ("stale_review", "payout_version_conflict"),
        ("missing_request", "payout_not_found"),
        ("unknown_action", "payout_review_approval_required"),
    ],
)
async def test_admin_command_cannot_skip_review_version_or_known_action(
    payout_env, case, code
):
    env = payout_env
    state = await env["execute"](request_command(env))
    change = {
        "start_unapproved": {"action": "start"},
        "stale_review": {"expected_version": 0},
        "missing_request": {"request_id": uuid4()},
        "unknown_action": {"action": "silently_pay"},
    }[case]
    with pytest.raises(ValueError, match=code):
        await env["execute"](
            replace(review_command(env, state, "review"), **change)
        )
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,code",
    [
        ("execution", "payout_execution_scope_invalid"),
        ("hash", "payout_bank_evidence_invalid"),
        ("status", "payout_bank_evidence_invalid"),
        ("evidence", "payout_evidence_reference_required"),
    ],
)
async def test_untrusted_bank_submission_cannot_fabricate_intent_or_review(
    payout_env, case, code
):
    env = payout_env
    state = await prepare(env)
    changes = {
        "execution": {"execution_id": uuid4()},
        "hash": {"evidence_hash": "not-a-hash"},
        "status": {"status": "automatic-success"},
        "evidence": {"evidence_reference": " "},
    }[case]
    with pytest.raises(ValueError, match=code):
        await env["execute"](result_command(env, state, **changes))
    assert wallet(env, env["flow"]["manager"])["reserved_minor"] == 60000


@pytest.mark.asyncio
async def test_future_or_disabled_requirements_never_silently_approve(
    payout_env,
):
    env = payout_env
    await env["execute"](
        replace(
            env["publication"],
            operation_key="disable-now",
            expected_version=env["requirements"]["version"],
            enabled=False,
        )
    )
    with pytest.raises(
        ValueError, match="published_payout_requirements_required"
    ):
        await env["execute"](request_command(env))


@pytest.mark.asyncio
async def test_lifecycle_guard_refusal_blocks_reservation_without_money_worker(
    payout_env, monkeypatch
):
    env = payout_env
    original = env["service"].work_guard.require_clear

    async def disputed(item_id, *, session):
        assert item_id == env["flow"]["item"]
        await original(item_id, session=session)
        raise ValueError("work_disputed")

    monkeypatch.setattr(env["service"].work_guard, "require_clear", disputed)
    with pytest.raises(ValueError, match="work_disputed"):
        await env["execute"](request_command(env))
    assert wallet(env, env["flow"]["manager"])["available_minor"] == 60000


@pytest.mark.asyncio
async def test_unrecognised_internal_command_does_not_default_to_money(
    payout_env,
):
    @dataclass
    class UnknownCommand:
        actor_id: UUID
        operation_key: str

    env = payout_env
    with pytest.raises(ValueError, match="payout_command_unknown"):
        await env["execute"](UnknownCommand(env["flow"]["manager"], "unknown"))


@pytest.mark.asyncio
async def test_wallet_mismatch_stops_payout_and_is_not_repaired(payout_env):
    from ugc_bot.infrastructure.db.base import Base

    env = payout_env
    table = Base.metadata.tables["financial_wallets"]
    try:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(table)
                .where(table.c.recipient_id == env["flow"]["manager"])
                .values(available_minor=60001)
            )
        with pytest.raises(
            ValueError, match="reconciliation_mismatch_audit_required"
        ):
            await env["execute"](request_command(env))
        assert wallet(env, env["flow"]["manager"])["available_minor"] == 60001
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(table)
                .where(table.c.recipient_id == env["flow"]["manager"])
                .values(available_minor=60000)
            )
