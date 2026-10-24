"""Synthetic pure approval behavior; SQL producer proof is separate."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from tests.helpers.correction_approvals import (
    NOW,
    U,
    captured_approval,
    early_report,
    environment,
    faithful_legacy_authority,
    match,
    observation,
    request,
    review,
)
from ugc_bot.application.correction_ports import CorrectionApplicationRefused
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_early_intent_approval_keeps_original_history(platform):
    env = environment(platform=platform)
    early, attached, retained, owners = await early_report(env)
    approved = await env.execute(review(attached))
    assert approved["intent_id"] == early["intent_id"]
    assert approved["approval_id"]
    result = await env.execute(match(approved, approved, early))
    assert result["approval_id"] == approved["approval_id"]
    assert result["application_status"] == "awaiting_assessment"
    assert result["applied"] is False
    assert len(env.repo.rows["approvals"]) == 1
    assert env.repo.rows["match_approvals"] == [
        dict(
            match_id=UUID(result["match_id"]),
            approval_id=UUID(approved["approval_id"]),
        )
    ]
    assert {kind: env.repo.rows[kind] for kind in retained} == retained
    assert env.proofs.rows == owners
    assert "applications" not in env.repo.rows


@pytest.mark.asyncio
async def test_null_early_case_uses_later_own_request_without_filling_case():
    env = environment()
    early, attached, retained, owners = await early_report(
        env, unknown_case_owner=True
    )
    approved = await env.execute(review(attached))
    result = await env.execute(match(approved, approved, early))
    assert result["application_status"] == "awaiting_assessment"
    assert retained["cases"][0]["client_id"] is None
    assert retained["cases"][0]["order_id"] is None
    assert {kind: env.repo.rows[kind] for kind in retained} == retained
    assert env.proofs.rows == owners


@pytest.mark.asyncio
async def test_captured_first_keeps_exact_original_source_capsule():
    env = environment()
    approved = await captured_approval(env)
    row = env.repo.rows["approvals"][0]
    assert row["capture_id"] == U[7]
    assert row["capture_id"] != row["source_capsule"]["invoice_intent_id"]
    assert row["client_id"] == U[0] and row["order_id"] == U[3]
    assert row["amount_minor"] == 50000 and row["currency"] == "RUB"
    assert row["bundle"][0]["gross_minor"] == 50000
    assert (
        row["bundle"][0]["selection_due_at"]
        == (NOW - timedelta(days=1)).isoformat()
    )
    assert row["source_capsule"]["quote_key"] == "synthetic:quote"
    assert row["source_capsule"]["terms_reference"] == "synthetic:terms"
    assert (
        row["source_capsule"]["invoice"]["payload"]["account"]
        == "synthetic-original-account"
    )
    assert (
        row["source_capsule"]["payment"]["external_id"] == "synthetic-payment"
    )
    assert env.repo.rows["intents"][0]["request_id"] is None
    assert str(env.repo.events[-1].source_id) == approved["approval_id"]
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    assert matched["approval_id"] == approved["approval_id"]
    assert env.repo.rows["matches"][0]["review_version"] == approved["version"]


@pytest.mark.asyncio
async def test_repeat_match_keeps_original_proof_and_effective_approval():
    env = environment()
    early, attached, retained, owners = await early_report(env)
    approved = await env.execute(review(attached))
    second = await env.execute(
        observation(approved, operation_key="second-report")
    )
    first_match = await env.execute(match(second, approved, second))
    last = await env.execute(
        match(first_match, approved, early, operation_key="next-match")
    )
    assert env.proofs.rows == owners
    assert env.repo.rows["observations"][0] == retained["observations"][0]
    assert len(env.repo.rows["approvals"]) == 1
    assert len(env.repo.rows["match_approvals"]) == 2
    assert {
        str(row["approval_id"]) for row in env.repo.rows["match_approvals"]
    } == {approved["approval_id"]}
    assert {row["review_version"] for row in env.repo.rows["matches"]} == {
        approved["version"]
    }
    assert last["version"] > approved["version"]
    with pytest.raises(ValueError, match="correction_version_conflict"):
        await env.execute(
            match(approved, approved, early, operation_key="stale-match")
        )


@pytest.mark.asyncio
async def test_new_review_invalidates_old_approval_for_new_match():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    rejected = await env.execute(
        review(observed, decision="reject", operation_key="reject")
    )
    with pytest.raises(ValueError, match="correction_approved_review_required"):
        await env.execute(match(rejected, approved, observed))
    again = await env.execute(review(rejected, operation_key="approve-again"))
    result = await env.execute(
        match(again, approved, observed, operation_key="new-reviewed-match")
    )
    assert again["intent_id"] == approved["intent_id"]
    assert again["approval_id"] != approved["approval_id"]
    assert result["approval_id"] == again["approval_id"]
    assert env.repo.rows["matches"][0]["review_version"] == again["version"]
    assert len(env.repo.rows["intents"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", U[10]),
        ("case_id", U[10]),
        ("request_id", U[10]),
        ("capture_id", U[4]),
        ("payment_id", U[10]),
        ("client_id", U[2]),
        ("order_id", U[10]),
        ("source_hash", "b" * 64),
        ("bundle", []),
        ("amount_minor", 49999),
        ("currency", "USD"),
        ("review_version", 999),
        ("review_version", True),
        ("command_id", U[10]),
        ("approval_id", U[10]),
        ("source_capsule", {}),
    ],
)
async def test_present_malformed_approval_never_falls_back_to_other_authority(
    field, value
):
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    env.repo.rows["approvals"][0][field] = value
    with pytest.raises(ValueError):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"] and not env.repo.rows["match_approvals"]


@pytest.mark.asyncio
async def test_complete_legacy_authority_needs_no_companion_link():
    env = environment()
    approved = await captured_approval(env)
    faithful_legacy_authority(env, approved)
    observed = await env.execute(observation(approved))
    before = deepcopy(env.repo.rows["intents"])
    result = await env.execute(match(observed, approved, observed))
    assert "approval_id" not in result
    assert result["application_status"] == "awaiting_assessment"
    assert (
        not env.repo.rows["approvals"] and not env.repo.rows["match_approvals"]
    )
    assert env.repo.rows["intents"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", None),
        ("capture_id", None),
        ("payment_id", None),
        ("bundle", None),
        ("source_hash", None),
        ("review_version", None),
    ],
)
async def test_partial_legacy_capsules_cannot_supply_positive_authority(
    field, value
):
    env = environment()
    approved = await captured_approval(env)
    faithful_legacy_authority(env, approved)
    env.repo.rows["intents"][0][field] = value
    observed = await env.execute(observation(approved))
    with pytest.raises(ValueError):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_request_as_review_shortcut_is_not_authenticated_as_legacy():
    env = environment()
    approved = await captured_approval(env)
    faithful_legacy_authority(env, approved)
    receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["operation_key"] == "review"
    )
    receipt["action"] = "RequestSelectionRefund"
    observed = await env.execute(observation(approved))
    with pytest.raises(ValueError, match="correction_approved_review_required"):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
async def test_present_approval_binding_is_not_ignored_to_use_complete_legacy():
    env = environment()
    approved = await captured_approval(env)
    row = deepcopy(env.repo.rows["approvals"][0])
    faithful_legacy_authority(env, approved)
    env.repo.rows["approvals"].append(row)
    observed = await env.execute(observation(approved))
    with pytest.raises(ValueError, match="correction_approved_review_required"):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "wrong", "extra"])
async def test_retained_new_match_requires_its_exact_immutable_approval_link(
    case,
):
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    if case == "missing":
        env.repo.rows["match_approvals"].clear()
    elif case == "wrong":
        env.repo.rows["match_approvals"][0]["approval_id"] = U[10]
    else:
        env.repo.rows["match_approvals"].append(
            dict(env.repo.rows["match_approvals"][0])
        )
    with pytest.raises(
        ValueError, match="correction_match_approval_unavailable"
    ):
        await env.execute(
            match(
                matched, approved, observed, operation_key="after-corrupt-link"
            )
        )
    assert len(env.repo.rows["matches"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["native", "admin", "status"])
async def test_current_native_and_admin_authority_precedes_new_approval_replay(
    case,
):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    principal = None
    if case == "native":
        principal = AuthenticatedMessengerPrincipal(U[1], "telegram", "stale")
    elif case == "admin":
        env.repo.actors[U[1]]["admin"] = False
    else:
        env.repo.actors[U[1]]["status"] = "blocked"
    before = deepcopy(env.repo.rows)
    env.repo.trace.clear()
    with pytest.raises(ValueError):
        await env.execute(command, principal=principal)
    assert env.repo.rows == before and "wallets" not in env.repo.trace


@pytest.mark.asyncio
async def test_new_match_uses_current_server_due_and_current_full_source():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved, occurred_at=None))
    env.service.clock = type(
        "Clock", (), {"now": staticmethod(lambda: NOW - timedelta(days=1))}
    )()
    with pytest.raises(ValueError, match="correction_selection_due_not_passed"):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("client_id", U[2]), ("order_id", U[10])]
)
async def test_foreign_nonnull_early_case_denies_before_wallet(field, value):
    env = environment()
    early, attached, _, _ = await early_report(env, unknown_case_owner=True)
    env.repo.rows["cases"][0][field] = value
    env.repo.trace.clear()
    before = deepcopy(env.repo.rows)
    with pytest.raises(ValueError):
        await env.execute(review(attached))
    assert env.repo.rows == before and "wallets" not in env.repo.trace
    assert early["intent_id"]


@pytest.mark.asyncio
async def test_old_link_survives_rejection_then_new_approval():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    old_rows = deepcopy(
        env.repo.rows["matches"] + env.repo.rows["match_approvals"]
    )
    rejected = await env.execute(
        review(matched, decision="reject", operation_key="reject")
    )
    fresh = await env.execute(review(rejected, operation_key="approve-again"))
    result = await env.execute(
        match(fresh, approved, observed, operation_key="new-match")
    )
    assert result["approval_id"] == fresh["approval_id"]
    assert fresh["approval_id"] != approved["approval_id"]
    assert (
        env.repo.rows["matches"][:1] + env.repo.rows["match_approvals"][:1]
        == old_rows
    )


@pytest.mark.asyncio
async def test_capture_authority_cannot_be_the_invoice_intent_identity():
    env = environment()
    env.repo.scope = replace(env.repo.scope, capture_id=U[4])
    own = await env.execute(request())
    before = deepcopy(env.repo.rows)
    with pytest.raises(
        ValueError, match="correction_original_payment_unavailable"
    ):
        await env.execute(review(own))
    assert env.repo.rows == before


@pytest.mark.asyncio
async def test_linked_old_approval_still_needs_its_genuine_review_command():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    fresh = await env.execute(review(matched, operation_key="another-review"))
    old_receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["operation_key"] == "review"
    )
    old_receipt["action"] = "RequestSelectionRefund"
    with pytest.raises(ValueError, match="correction_approved_review_required"):
        await env.execute(
            match(fresh, fresh, observed, operation_key="after-corrupt-review")
        )
    assert len(env.repo.rows["matches"]) == 1


@pytest.mark.asyncio
async def test_stripped_link_cannot_turn_new_match_into_legacy():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    env.repo.rows["match_approvals"].clear()
    receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["operation_key"] == "match"
    )
    receipt["result"].pop("approval_id")
    with pytest.raises(
        ValueError, match="correction_match_approval_unavailable"
    ):
        await env.execute(
            match(
                matched, approved, observed, operation_key="forged-legacy-match"
            )
        )
    assert len(env.repo.rows["matches"]) == 1


@pytest.mark.asyncio
async def test_legacy_match_keeps_original_receipt_without_backfill():
    env = environment()
    approved = await captured_approval(env)
    faithful_legacy_authority(env, approved)
    observed = await env.execute(observation(approved))
    original = await env.execute(match(observed, approved, observed))
    retained = deepcopy(env.repo.rows)
    owners = deepcopy(env.proofs.rows)
    result = await env.execute(
        match(original, approved, observed, operation_key="new-legacy-match")
    )
    assert "approval_id" not in result
    assert env.repo.rows["commands"][:-1] == retained["commands"]
    assert env.repo.rows["matches"][:-1] == retained["matches"]
    assert env.proofs.rows == owners
    assert (
        not env.repo.rows["approvals"] and not env.repo.rows["match_approvals"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 30])
async def test_full_original_selection_bundle_is_required_for_whole_refund(
    count,
):
    env = environment()
    component = env.repo.scope.bundle.components[0]
    items = tuple(UUID(int=1000 + index) for index in range(count))
    components = tuple(
        replace(
            component,
            paid_item_id=item,
            allocation_key=f"synthetic:selection:{item}",
        )
        for item in items
    )
    env.repo.scope = replace(
        env.repo.scope,
        bundle=replace(env.repo.scope.bundle, components=components),
        selected_paid_item_ids=items,
    )
    own = await env.execute(request(paid_item_ids=items))
    approved = await env.execute(review(own))
    observed = await env.execute(
        observation(approved, amount_minor=count * 50000)
    )
    matched = await env.execute(match(observed, approved, observed))
    row = env.repo.rows["approvals"][0]
    assert row["amount_minor"] == count * 50000
    assert len(row["bundle"]) == count
    assert matched["applied"] is False
    assert row["capture_id"] == U[7]


@pytest.mark.asyncio
async def test_link_refusal_rolls_back_match_and_keeps_old_proof():
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    before = deepcopy(env.repo.rows["observations"])
    owners = deepcopy(env.proofs.rows)
    append = env.repo.append_fact

    async def reject_link(name, values, *, session):
        if name == "match_approvals":
            raise CorrectionApplicationRefused("synthetic relation refusal")
        await append(name, values, session=session)

    env.repo.append_fact = reject_link
    result = await env.execute(match(observed, approved, observed))
    assert result["application_status"] == "unavailable"
    assert not env.repo.rows["matches"] and not env.repo.rows["match_approvals"]
    assert env.repo.rows["observations"] == before and env.proofs.rows == owners


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["intent_id", "case_id"])
async def test_orphan_observation_does_not_gain_authority_from_new_approval(
    field,
):
    env = environment()
    approved = await captured_approval(env)
    observed = await env.execute(observation(approved))
    env.repo.rows["observations"][0][field] = None
    with pytest.raises(ValueError):
        await env.execute(match(observed, approved, observed))
    assert not env.repo.rows["matches"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["action", "actor", "event", "result"])
async def test_new_approval_needs_real_own_request_command_and_event(case):
    env = environment()
    own = await env.execute(request())
    receipt = env.repo.rows["commands"][0]
    if case == "action":
        receipt["action"] = "ReviewSelectionRefund"
    elif case == "actor":
        receipt["actor_id"] = U[2]
    elif case == "event":
        env.repo.events[0] = replace(env.repo.events[0], source_id=U[10])
    else:
        receipt["result"]["request_id"] = str(U[10])
    before = deepcopy(env.repo.rows)
    with pytest.raises(ValueError, match="correction_request_scope_invalid"):
        await env.execute(review(own))
    assert env.repo.rows == before
