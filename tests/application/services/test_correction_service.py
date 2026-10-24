"""Declared synthetic source orchestration; no SQL or provider evidence."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from tests.helpers.correction_commands import HASH, NOW, U, environment, request
from ugc_bot.application.correction_ports import (
    CorrectionApplicationRefused,
    MatchSelectionRefund,
    RecordManualRefundObservation,
    ReviewSelectionRefund,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


def review(result, **changes):
    return ReviewSelectionRefund(
        **(
            dict(
                actor_id=U[1],
                operation_key="review",
                reason="Synthetic actual admin review",
                case_id=UUID(result["case_id"]),
                expected_version=result["version"],
                expected_source_hash=HASH,
                decision="approve",
                evidence_reference="synthetic:review",
                evidence_hash=HASH,
            )
            | changes
        )
    )


def observation(result=None, **changes):
    return RecordManualRefundObservation(
        **(
            dict(
                actor_id=U[1],
                operation_key="observation",
                reason="Synthetic actual manual report",
                case_id=UUID(result["case_id"]) if result else None,
                known_order_id=U[3],
                known_capture_intent_id=U[4],
                original_payment_reference="synthetic-payment",
                bank_account_label="synthetic-bank",
                bank_reference="synthetic:refund",
                amount_minor=50000,
                currency="RUB",
                occurred_at=NOW,
                reported_component="selection",
                evidence_reference="synthetic:observation",
                evidence_hash=HASH,
                expected_version=result["version"] if result else None,
            )
            | changes
        )
    )


def match(result, intent, observed, **changes):
    return MatchSelectionRefund(
        **(
            dict(
                actor_id=U[1],
                operation_key="match",
                reason="Synthetic exact fresh match",
                case_id=UUID(result["case_id"]),
                intent_id=UUID(intent["intent_id"]),
                observation_id=UUID(observed["observation_id"]),
                expected_version=result["version"],
                expected_source_hash=HASH,
                evidence_reference="synthetic:match",
                evidence_hash=HASH,
            )
            | changes
        )
    )


async def approved(env):
    return await env.execute(review(await env.execute(request())))


@pytest.mark.asyncio
async def test_complete_flow_awaits_real_compensation_assessment():
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    result = await env.execute(match(observed, intent, observed))
    assert result["application_status"] == "awaiting_assessment"
    assert result["match_status"] == "matched"
    assert len(env.repo.rows["matches"]) == 1
    assert "applications" not in env.repo.rows
    assert len(env.proofs.rows) == 1
    owner = next(iter(env.proofs.rows.values()))
    assert owner.intent_id == UUID(intent["intent_id"])
    assert owner.observation_id == UUID(observed["observation_id"])
    assert (
        env.repo.trace.index("barrier")
        < env.repo.trace.index("actor")
        < env.repo.trace.index("receipt")
    )


@pytest.mark.asyncio
async def test_original_receipt_replays_while_fresh_state_is_separate():
    env = environment()
    command = request()
    original = await env.execute(command)
    current = await env.execute(review(original))
    assert await env.execute(command) == original
    status = await env.service.operation_for_actor(
        U[0], command.operation_key, session=env.repo.session
    )
    assert status["original_result"] == original
    assert status["current"]["version"] == current["version"]
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await env.execute(replace(command, reason="Different retained reason"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["native", "admin", "blocked", "foreign", "changed"]
)
async def test_current_authority_precedes_private_replay_and_mutation(case):
    env = environment()
    result = await env.execute(request())
    before = deepcopy(env.repo.rows)
    command, principal = review(result), None
    if case == "native":
        principal = AuthenticatedMessengerPrincipal(U[1], "telegram", "old")
    elif case == "admin":
        env.repo.actors[U[1]]["admin"] = False
    elif case == "blocked":
        env.repo.actors[U[1]]["status"] = "blocked"
    elif case == "foreign":
        command = request(actor_id=U[2], operation_key="foreign")
    else:
        env.repo.changed = True
    with pytest.raises(ValueError):
        await env.execute(command, principal=principal)
    assert env.repo.rows == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("assignment_ids", (U[9],)),
        ("accepted_delivery_ids", (U[9],)),
        ("selection_due_at", NOW),
    ],
)
async def test_ineligible_own_request_retains_review_evidence_without_intent(
    field, value
):
    env = environment()
    component = replace(env.repo.scope.bundle.components[0], **{field: value})
    env.repo.scope = replace(
        env.repo.scope,
        bundle=replace(env.repo.scope.bundle, components=(component,)),
    )
    result = await env.execute(request())
    assert result["blockers"] and result["review_status"] == "pending"
    assert len(env.repo.rows["requests"]) == 1
    with pytest.raises(ValueError):
        await env.execute(review(result))
    assert not env.repo.rows["intents"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"amount_minor": None, "currency": None},
        {"amount_minor": -5, "currency": "USD"},
        {"amount_minor": 0},
        {"reported_component": "management"},
    ],
)
async def test_unsupported_actual_observations_remain_true_and_owned(changes):
    env = environment()
    env.repo.scope = replace(
        env.repo.scope,
        bundle=None,
        payment_id=None,
        capture_id=None,
        source_hash=None,
        unavailable_reason="correction_capture_unavailable",
    )
    command = observation(**changes)
    result = await env.execute(command)
    stored = env.repo.rows["observations"][0]
    assert stored["amount_minor"] == command.amount_minor
    assert stored["currency"] == command.currency
    assert result["match_status"] == "unmatched"
    assert len(env.proofs.rows) == 1
    assert all(
        row["capture_id"] is None and row["request_id"] is None
        for row in env.repo.rows["intents"]
    )


@pytest.mark.asyncio
async def test_early_owner_is_never_updated_or_replaced_by_later_request():
    env = environment()
    env.repo.scope = replace(
        env.repo.scope,
        bundle=None,
        payment_id=None,
        capture_id=None,
        source_hash=None,
        unavailable_reason="correction_capture_unavailable",
    )
    early = await env.execute(observation())
    before = deepcopy(env.repo.rows["observations"])
    intents = deepcopy(env.repo.rows["intents"])
    claims = deepcopy(env.proofs.rows)
    env.repo.scope = env.repo.captured
    attached = await env.execute(
        request(existing_case_id=UUID(early["case_id"]))
    )
    reviewed = await env.execute(review(attached))
    assert reviewed["intent_id"] == early["intent_id"]
    assert reviewed["approval_id"]
    assert len(env.repo.rows["approvals"]) == 1
    assert env.repo.rows["observations"] == before
    assert env.repo.rows["intents"] == intents
    assert env.proofs.rows == claims


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stale", "projection", "source"])
async def test_actual_observation_survives_expected_refusal(case):
    env = environment()
    intent = await approved(env)
    if case == "projection":
        env.repo.consistent = False
    if case == "source":
        env.proofs.available = False
    result = await env.execute(observation(intent, expected_version=1))
    assert not result.get("applied", False)
    assert len(env.repo.rows["observations"]) == 1
    assert result["blockers"]
    if case == "projection":
        assert result["state_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("unexpected", [False, True])
async def test_match_refusal_is_narrow_and_keeps_outer_observation(unexpected):
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    env.repo.refusal = (
        RuntimeError("synthetic database failure")
        if unexpected
        else CorrectionApplicationRefused("synthetic expected refusal")
    )
    if unexpected:
        with pytest.raises(RuntimeError):
            await env.execute(match(observed, intent, observed))
    else:
        result = await env.execute(match(observed, intent, observed))
        assert result["application_status"] == "unavailable"
    assert len(env.repo.rows["observations"]) == 1
    assert len(env.proofs.rows) == 1
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_fresh_matches_keep_actual_effective_approval_and_owner():
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    matched = await env.execute(match(observed, intent, observed))
    assert env.repo.rows["matches"][0]["review_version"] == intent["version"]
    owner = deepcopy(env.proofs.rows)
    second = await env.execute(
        match(matched, intent, observed, operation_key="second-match")
    )
    assert second["application_status"] == "awaiting_assessment"
    assert len(env.repo.rows["matches"]) == 2
    assert all(
        row["review_version"] == intent["version"]
        for row in env.repo.rows["matches"]
    )
    assert env.proofs.rows == owner


@pytest.mark.asyncio
async def test_revoked_admin_cannot_read_old_privileged_operation():
    env = environment()
    intent = await approved(env)
    env.repo.actors[U[1]]["admin"] = False
    with pytest.raises(ValueError, match="correction_active_admin_required"):
        await env.service.operation_for_actor(
            U[1], "review", session=env.repo.session
        )
    assert intent["review_status"] == "approved"


@pytest.mark.asyncio
async def test_changed_owner_cannot_read_old_own_case_or_operation():
    env = environment()
    own = await env.execute(request())
    env.repo.scope = replace(env.repo.scope, client_id=U[2])
    with pytest.raises(ValueError, match="correction_own_client_required"):
        await env.service.get_for_actor(
            UUID(own["case_id"]), U[0], session=env.repo.session
        )
    with pytest.raises(ValueError, match="correction_own_client_required"):
        await env.service.operation_for_actor(
            U[0], "request", session=env.repo.session
        )


@pytest.mark.asyncio
async def test_rejection_does_not_clear_actual_observation_or_its_blockers():
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent, currency="USD"))
    before, claims = (
        deepcopy(env.repo.rows["observations"]),
        deepcopy(env.proofs.rows),
    )
    rejected = await env.execute(
        review(observed, operation_key="reject", decision="reject")
    )
    assert rejected["review_status"] == "rejected"
    assert (
        "correction_observation_economics_unavailable" in rejected["blockers"]
    )
    assert env.repo.rows["observations"] == before
    assert env.proofs.rows == claims


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("order_id", U[10]), ("client_id", U[2]), ("paid_item_ids", [str(U[10])])],
)
async def test_corrupt_request_routing_cannot_receive_approval(field, value):
    env = environment()
    own = await env.execute(request())
    env.repo.rows["requests"][0][field] = value
    with pytest.raises(ValueError, match="correction_request_scope_invalid"):
        await env.execute(review(own))
    assert not env.repo.rows["intents"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_minor", 49999),
        ("currency", "USD"),
        ("reported_component", "unknown"),
        ("original_payment_reference", "other-payment"),
        ("known_order_id", U[10]),
        ("known_capture_intent_id", U[10]),
    ],
)
async def test_exact_match_refuses_corrupt_or_nonmatching_actual_fact(
    field, value
):
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    env.repo.rows["observations"][0][field] = value
    with pytest.raises(ValueError):
        await env.execute(match(observed, intent, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_own_and_admin_reads_use_current_authority_and_separate_facts():
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    own = await env.service.get_for_actor(
        UUID(intent["case_id"]), U[0], session=env.repo.session
    )
    admin = await env.service.get_for_actor(
        UUID(intent["case_id"]), U[1], session=env.repo.session
    )
    assert own["current"]["version"] == observed["version"]
    assert "observations" not in own and len(admin["observations"]) == 1
    assert "synthetic-bank" not in str(own)
    absent = await env.service.operation_for_actor(
        U[0], "not-issued", session=env.repo.session
    )
    assert absent == dict(recorded=False, original_result=None, current=None)
    env.repo.consistent = False
    unavailable = await env.service.get_for_actor(
        UUID(intent["case_id"]), U[1], session=env.repo.session
    )
    assert unavailable["current"] is None and unavailable["state_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("occurred", [None, NOW + timedelta(days=1)])
async def test_reported_bank_time_never_replaces_server_due_clock(occurred):
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent, occurred_at=occurred))
    result = await env.execute(match(observed, intent, observed))
    assert result["application_status"] == "awaiting_assessment"
    assert env.repo.rows["observations"][0]["occurred_at"] == occurred


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "action",
        "result_intent",
        "result_version",
        "event_command",
        "event_actor",
    ],
)
async def test_match_requires_genuine_exact_approval_receipt_and_event(case):
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["operation_key"] == "review"
    )
    if case == "action":
        receipt["action"] = "RequestSelectionRefund"
    elif case == "result_intent":
        receipt["result"]["intent_id"] = str(U[10])
    elif case == "result_version":
        receipt["result"]["version"] = 999
    else:
        field = "command_id" if case == "event_command" else "actor_id"
        env.repo.events[1] = replace(env.repo.events[1], **{field: U[10]})
    with pytest.raises(ValueError):
        await env.execute(match(observed, intent, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_original_proof_owner_must_link_to_the_same_physical_key():
    env = environment()
    intent = await approved(env)
    first = await env.execute(observation(intent))
    first_owner = next(iter(env.proofs.rows.values()))
    second = await env.execute(
        observation(
            first,
            operation_key="second-observation",
            bank_reference="synthetic:second",
        )
    )
    second_key = env.proofs.resolve_manual_identity(
        "synthetic-bank", "synthetic:second", direction="outgoing"
    )
    env.proofs.rows[second_key.key] = first_owner
    with pytest.raises(
        ValueError, match="correction_physical_proof_unavailable"
    ):
        await env.execute(match(second, intent, second))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("source_hash", "b" * 64), ("bundle", [])]
)
async def test_request_source_capsule_must_match_the_current_full_bundle(
    field, value
):
    env = environment()
    own = await env.execute(request())
    env.repo.rows["requests"][0][field] = value
    with pytest.raises(ValueError, match="correction_request_scope_invalid"):
        await env.execute(review(own))
    assert not env.repo.rows["intents"]


@pytest.mark.asyncio
async def test_paused_admin_cannot_read_privileged_case_facts():
    env = environment()
    own = await env.execute(request())
    env.repo.actors[U[1]]["status"] = "pause"
    with pytest.raises(ValueError, match="correction_active_admin_required"):
        await env.service.get_for_actor(
            UUID(own["case_id"]), U[1], session=env.repo.session
        )


@pytest.mark.asyncio
async def test_new_same_intent_report_preserves_original_owner_attribution():
    env = environment()
    intent = await approved(env)
    first = await env.execute(observation(intent))
    owner = deepcopy(env.proofs.rows)
    second = await env.execute(
        observation(first, operation_key="same-proof-second-report")
    )
    result = await env.execute(match(second, intent, second))
    assert result["application_status"] == "awaiting_assessment"
    assert env.proofs.rows == owner
    assert next(iter(owner.values())).observation_id == UUID(
        first["observation_id"]
    )
    assert env.repo.rows["matches"][0]["observation_id"] == UUID(
        second["observation_id"]
    )


@pytest.mark.asyncio
async def test_foreign_physical_owner_retains_the_actual_report_only():
    from ugc_bot.application.physical_proof_ports import PhysicalProofOwner

    env = environment()
    intent = await approved(env)
    key = env.proofs.resolve_manual_identity(
        "synthetic-bank", "synthetic:refund", direction="outgoing"
    )
    original = PhysicalProofOwner(
        producer="payout",
        intent_id=U[10],
        observation_id=U[11],
        command_id=U[12],
    )
    env.proofs.rows[key.key] = original
    observed = await env.execute(observation(intent))
    assert "correction_physical_proof_conflict" in observed["blockers"]
    assert len(env.repo.rows["observations"]) == 1
    with pytest.raises(ValueError, match="correction_physical_proof_conflict"):
        await env.execute(match(observed, intent, observed))
    assert env.proofs.rows[key.key] == original
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("case_id", U[10]), ("intent_id", U[10])]
)
async def test_original_observation_receipt_cannot_be_relinked(field, value):
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["operation_key"] == "observation"
    )
    receipt["result"][field] = str(value)
    with pytest.raises(
        ValueError, match="correction_physical_proof_unavailable"
    ):
        await env.execute(match(observed, intent, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_unavailable_captured_source_cannot_receive_admin_approval():
    env = environment()
    own = await env.execute(request())
    env.repo.scope = replace(
        env.repo.scope, unavailable_reason="correction_source_unavailable"
    )
    with pytest.raises(ValueError, match="correction_source_unavailable"):
        await env.execute(review(own))
    assert not env.repo.rows["intents"]


@pytest.mark.asyncio
async def test_missing_configured_proof_retains_fact_and_refuses_later_match():
    env = environment()
    intent = await approved(env)
    observed = await env.execute(observation(intent))
    original = deepcopy(env.repo.rows["observations"])
    env.proofs.available = False
    with pytest.raises(
        ValueError, match="correction_physical_proof_unavailable"
    ):
        await env.execute(match(observed, intent, observed))
    assert env.repo.rows["observations"] == original
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "case", "operation"])
async def test_complete_users_precede_actor_then_wallets_and_private_scope(
    entry,
):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    env.repo.trace.clear()
    if entry == "execute":
        await env.execute(command)
    elif entry == "case":
        await env.service.get_for_actor(
            UUID(own["case_id"]), U[1], session=env.repo.session
        )
    else:
        await env.service.operation_for_actor(
            U[1], command.operation_key, session=env.repo.session
        )
    trace = env.repo.trace
    users = ("users", tuple(sorted(env.repo.scope.prospective_user_ids)))
    assert users in trace
    assert trace.index(users) < trace.index("actor") < trace.index("wallets")
    assert trace.index("wallets") < trace.index("reread")
    if entry != "execute":
        assert trace.index("actor") < trace.index("read_authority")
        assert trace.index("read_authority") < trace.index("wallets")


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["case", "operation"])
async def test_foreign_case_or_own_operation_denies_before_wallets_or_source(
    entry,
):
    env = environment()
    own = await env.execute(request())
    env.repo.changed = True
    env.repo.trace.clear()
    if entry == "operation":
        env.repo.scope = replace(env.repo.scope, client_id=U[2])
    with pytest.raises(ValueError, match="^correction_own_client_required$"):
        if entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[2], session=env.repo.session
            )
        else:
            await env.service.operation_for_actor(
                U[0], "request", session=env.repo.session
            )
    assert "wallets" not in env.repo.trace
    assert "reread" not in env.repo.trace
    assert "facts" not in env.repo.trace and "receipt" not in env.repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["case", "operation"])
async def test_authorized_private_reads_keep_whole_transaction_source_retry(
    entry,
):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    env.repo.changed = True
    env.repo.trace.clear()
    with pytest.raises(
        ValueError, match="^correction_scope_changed_retry_required$"
    ):
        if entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[1], session=env.repo.session
            )
        else:
            await env.service.operation_for_actor(
                U[1], command.operation_key, session=env.repo.session
            )
    assert env.repo.trace.index("actor") < env.repo.trace.index("wallets")
    assert "facts" not in env.repo.trace and "receipt" not in env.repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "case", "operation"])
async def test_current_ownership_is_reread_after_complete_users_before_wallets(
    entry,
):
    env = environment()
    command = request()
    own = await env.execute(command)
    original_prepare = env.repo.prepare_users

    async def change_owner(scope, *, session):
        await original_prepare(scope, session=session)
        env.repo.scope = replace(env.repo.scope, client_id=U[2])

    env.repo.prepare_users = change_owner
    env.repo.trace.clear()
    with pytest.raises(ValueError, match="^correction_own_client_required$"):
        if entry == "execute":
            await env.execute(command)
        elif entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[0], session=env.repo.session
            )
        else:
            await env.service.operation_for_actor(
                U[0], "request", session=env.repo.session
            )
    assert "wallets" not in env.repo.trace
    assert "facts" not in env.repo.trace and "receipt" not in env.repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["case", "operation", "review"])
@pytest.mark.parametrize(
    "field,value", [("client_id", U[2]), ("order_id", U[9])]
)
async def test_authorized_admin_checks_present_case_bindings_before_wallets(
    entry, field, value
):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    env.repo.rows["cases"][0][field] = value
    env.repo.trace.clear()
    with pytest.raises(ValueError, match="^correction_case_scope_invalid$"):
        if entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[1], session=env.repo.session
            )
        elif entry == "operation":
            await env.service.operation_for_actor(
                U[1], "review", session=env.repo.session
            )
        else:
            await env.execute(command)
    assert env.repo.trace.index("actor") < env.repo.trace.index(
        "read_authority"
    )
    assert "wallets" not in env.repo.trace and "reread" not in env.repo.trace
    assert "facts" not in env.repo.trace and "receipt" not in env.repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["native", "foreign", "admin"])
async def test_binding_conflict_never_preempts_current_action_denial(denial):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    env.repo.rows["cases"][0].update(client_id=U[2], order_id=U[9])
    env.repo.trace.clear()
    expected = {
        "native": "financial_principal_changed",
        "foreign": "correction_own_client_required",
        "admin": "correction_active_admin_required",
    }[denial]
    with pytest.raises(ValueError, match=f"^{expected}$"):
        if denial == "native":
            await env.service.get_for_actor(
                UUID(own["case_id"]),
                U[1],
                session=env.repo.session,
                principal=AuthenticatedMessengerPrincipal(U[1], "max", "old"),
            )
        elif denial == "foreign":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[2], session=env.repo.session
            )
        else:
            env.repo.actors[U[1]]["admin"] = False
            await env.service.operation_for_actor(
                U[1], "review", session=env.repo.session
            )
    assert "wallets" not in env.repo.trace and "reread" not in env.repo.trace
    assert "facts" not in env.repo.trace and "receipt" not in env.repo.trace
