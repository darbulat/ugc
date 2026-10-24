"""Pure immutable evidence, trusted source contracts and physical identity."""

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
U = tuple(UUID(int=i) for i in range(1, 31))
HASH = "a" * 64


def command_values():
    return dict(actor_id=U[0], operation_key="refund:1", reason="Due expired")


def request(**changes):
    from ugc_bot.application.correction_ports import RequestSelectionRefund

    values = dict(
        **command_values(),
        order_id=U[1],
        paid_item_ids=(U[3], U[2]),
        expected_source_hash=HASH,
    )
    values.update(changes)
    return RequestSelectionRefund(**values)


def state(**changes):
    from ugc_bot.domain.corrections import CorrectionState

    values = dict(case_id=U[4], version=1, source_hash=HASH)
    values.update(changes)
    return CorrectionState(**values)


def event(result=None, **changes):
    from ugc_bot.domain.corrections import CorrectionEvent

    result = result or state()
    values = dict(
        event_id=U[5],
        case_id=result.case_id,
        version=result.version,
        command_id=U[6],
        source_id=U[7],
        source_hash=result.source_hash,
        actor_id=U[0],
        reason="Exact reviewed scope",
        evidence_reference="protected:evidence",
        evidence_hash=HASH,
        recorded_at=NOW,
        previous_state_hash=None,
        result_state=result,
        result_state_hash=result.payload_hash,
    )
    values.update(changes)
    return CorrectionEvent(**values)


def component(**changes):
    from ugc_bot.domain.corrections import CapturedSelectionComponent

    values = dict(
        allocation_key="selection:item-1",
        payment_id=U[8],
        paid_item_id=U[9],
        gross_minor=50_000,
        currency="RUB",
        selection_due_at=NOW - timedelta(days=1),
        due_evidence_hash=HASH,
    )
    values.update(changes)
    return CapturedSelectionComponent(**values)


def assessment_line(**changes):
    from ugc_bot.application.correction_ports import OriginalAssessmentLine

    values = dict(
        paid_item_id=U[9],
        allocation_key="selection:item-1",
        base_minor=50_000,
        currency="RUB",
        status="issued",
        business_key="client-selection:payment:item-1",
        snapshot_id=U[10],
        obligation_id=U[11],
        issuance_entry_id=U[12],
        recipient_id=U[13],
        frozen_rate_bps=1000,
        liability_minor=5000,
    )
    values.update(changes)
    return OriginalAssessmentLine(**values)


def test_request_has_canonical_unique_immutable_selection_and_native_alias():
    from ugc_bot.application.correction_ports import (
        CorrectionPrincipal,
        correction_command_hash,
    )
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    value = request()
    assert value.paid_item_ids == (U[2], U[3])
    assert CorrectionPrincipal is AuthenticatedMessengerPrincipal
    assert correction_command_hash(value) == correction_command_hash(
        request(paid_item_ids=(U[2], U[3]))
    )
    assert correction_command_hash(value) != correction_command_hash(
        request(expected_source_hash="b" * 64)
    )
    assert "principal" not in asdict(value)
    with pytest.raises(FrozenInstanceError):
        value.reason = "changed"


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": UUID(int=0)},
        {"actor_id": str(U[0])},
        {"order_id": UUID(int=0)},
        {"existing_case_id": "forged"},
        {"paid_item_ids": ()},
        {"paid_item_ids": (U[2], U[2])},
        {"paid_item_ids": [U[2]]},
        {"paid_item_ids": ("forged",)},
        {"paid_item_ids": tuple(UUID(int=i + 1) for i in range(31))},
        {"operation_key": " "},
        {"operation_key": "x" * 257},
        {"reason": " "},
        {"reason": 1},
        {"expected_source_hash": "wrong"},
        {"expected_source_hash": "A" * 64},
    ],
)
def test_request_rejects_untyped_unbounded_and_mutable_inputs(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_review_and_match_freeze_exact_version_and_evidence():
    from ugc_bot.application.correction_ports import (
        MatchSelectionRefund,
        ReviewSelectionRefund,
        correction_command_hash,
    )

    review = ReviewSelectionRefund(
        **command_values(),
        case_id=U[4],
        expected_version=1,
        expected_source_hash=HASH,
        decision="reject",
        evidence_reference="protected:1",
        evidence_hash=HASH,
    )
    match = MatchSelectionRefund(
        **command_values(),
        case_id=U[4],
        intent_id=U[5],
        observation_id=U[6],
        expected_version=2,
        expected_source_hash=HASH,
        evidence_reference="protected:2",
        evidence_hash=HASH,
    )
    assert review.decision == "reject"
    assert correction_command_hash(review) != correction_command_hash(match)
    for value, changes in (
        (review, {"decision": "confirm"}),
        (review, {"expected_version": True}),
        (review, {"expected_version": 0}),
        (review, {"evidence_hash": "bad"}),
        (match, {"intent_id": UUID(int=0)}),
        (match, {"evidence_reference": " "}),
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)


def test_manual_observation_retains_early_missing_economic_facts():
    from ugc_bot.application.correction_ports import (
        RecordManualRefundObservation,
        correction_command_hash,
    )

    value = RecordManualRefundObservation(
        **command_values(),
        case_id=None,
        known_order_id=U[1],
        known_capture_intent_id=None,
        original_payment_reference="actual-provider-reference",
        bank_account_label="unrecognized caller label",
        bank_reference="actual-bank-reference",
        amount_minor=None,
        currency=None,
        occurred_at=None,
        reported_component="unknown",
        evidence_reference="protected:bank-1",
        evidence_hash=HASH,
        expected_version=None,
    )
    assert value.amount_minor is None
    assert value.provenance == "manual_admin_observation"
    complete = replace(
        value,
        amount_minor=50_000,
        currency="RUB",
        occurred_at=NOW.astimezone(timezone(timedelta(hours=3))),
        expected_version=1,
        reported_component="selection",
    )
    assert complete.occurred_at == NOW
    assert complete.occurred_at.tzinfo is timezone.utc
    assert correction_command_hash(complete) != correction_command_hash(value)
    for changes in (
        {"amount_minor": True},
        {"amount_minor": 1.1},
        {"amount_minor": 2**63},
        {"amount_minor": -(2**63) - 1},
        {"occurred_at": datetime(2026, 1, 1)},
        {"currency": True},
        {"reported_component": "fake"},
        {"known_order_id": "fake"},
        {"expected_version": -1},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)


def test_replay_preserves_successful_observation_across_request_rejection():
    from ugc_bot.domain.corrections import replay_correction_events

    first = state(observation_ids=(U[6],), blockers=("awaiting_review",))
    rejected = replace(first, version=2, review_status="rejected")
    result = replay_correction_events(
        (event(first), event(rejected, previous_state_hash=first.payload_hash))
    )
    assert result.review_status == "rejected"
    assert result.observation_ids == (U[6],)
    assert result.blockers == ("awaiting_review",)
    assert result.application_status == "unapplied"


@pytest.mark.parametrize(
    "change",
    ["empty", "gap", "case", "previous", "source", "result", "removed"],
)
def test_replay_rejects_a_broken_full_state_chain(change):
    from ugc_bot.domain.corrections import replay_correction_events

    first = state(observation_ids=(U[6],))
    second = replace(first, version=2)
    values = dict(previous_state_hash=first.payload_hash)
    if change == "gap":
        second = replace(second, version=3)
    elif change == "case":
        second = replace(second, case_id=U[15])
    elif change == "previous":
        values["previous_state_hash"] = "b" * 64
    elif change == "source":
        values["source_hash"] = "b" * 64
    elif change == "result":
        values["result_state_hash"] = "b" * 64
    elif change == "removed":
        second = replace(second, observation_ids=())
    with pytest.raises(ValueError):
        events = (
            () if change == "empty" else (event(first), event(second, **values))
        )
        replay_correction_events(events)


@pytest.mark.parametrize(
    "changes",
    [
        {"case_id": "fake"},
        {"version": True},
        {"version": 0},
        {"source_hash": "fake"},
        {"request_status": "fake"},
        {"review_status": "fake"},
        {"match_status": "fake"},
        {"application_status": "fake"},
        {"observation_ids": [U[6]]},
        {"blockers": ["unresolved"]},
        {"blockers": ("",)},
    ],
)
def test_state_rejects_mutable_and_noncanonical_full_results(changes):
    with pytest.raises(ValueError):
        state(**changes)


def test_event_validates_provenance_utc_and_typed_full_result():
    value = event(recorded_at=NOW.astimezone(timezone(timedelta(hours=3))))
    assert value.recorded_at.tzinfo is timezone.utc
    for changes in (
        {"recorded_at": datetime(2026, 1, 1)},
        {"actor_id": UUID(int=0)},
        {"evidence_reference": " "},
        {"result_state": asdict(state())},
        {"version": True},
        {"previous_state_hash": "bad"},
    ):
        with pytest.raises(ValueError):
            event(**changes)


def test_funding_uses_applied_facts_or_explicit_unavailable():
    from ugc_bot.domain.corrections import ComponentFunding

    value = ComponentFunding(
        allocation_key="original:selection",
        payment_id=U[8],
        paid_item_id=U[9],
        component="selection",
        currency="RUB",
        gross_minor=50_000,
        cumulative_refund_minor=50_000,
        net_minor=0,
        unresolved_observation_ids=(U[6],),
        unresolved_case_ids=(U[4],),
    )
    assert value.net_minor == 0
    assert (
        replace(value, state_consistent=False, net_minor=None).net_minor is None
    )
    for changes in (
        {"net_minor": 1},
        {"net_minor": None},
        {"gross_minor": True},
        {"cumulative_refund_minor": 50_001},
        {"state_consistent": False},
        {"state_consistent": 1},
        {"component": "fake"},
        {"currency": "USD"},
        {"unresolved_case_ids": [U[4]]},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)


def test_full_bundle_binds_all_original_selected_components_and_due_facts():
    from ugc_bot.domain.corrections import SelectionRefundBundle

    bundle = SelectionRefundBundle(components=(component(),))
    assert bundle.total_minor == 50_000
    assert bundle.positive_a1_refusal(NOW) is None
    for changes, want in (
        ({"selection_due_at": None}, "selection_due_unavailable"),
        ({"due_evidence_hash": None}, "selection_due_unavailable"),
        ({"selection_due_at": NOW}, "selection_due_not_passed"),
        ({"assignment_ids": (U[17],)}, "selection_previously_assigned"),
        ({"accepted_delivery_ids": (U[18],)}, "selection_already_delivered"),
        ({"gross_minor": 49_999}, "full_selection_component_required"),
    ):
        changed = SelectionRefundBundle(components=(component(**changes),))
        assert changed.positive_a1_refusal(NOW) == want
    for parts in ((), [component()], (component(), component())):
        with pytest.raises(ValueError):
            SelectionRefundBundle(components=parts)
    for changes in (
        {"allocation_key": " "},
        {"payment_id": UUID(int=0)},
        {"gross_minor": 2**63},
        {"currency": "USD"},
        {"due_evidence_hash": "bad"},
        {"selection_due_at": datetime(2026, 1, 1)},
        {"assignment_ids": [U[17]]},
    ):
        with pytest.raises(ValueError):
            component(**changes)


def test_original_assessment_uses_actual_ids_without_a_success_receipt():
    from ugc_bot.application.correction_ports import OriginalGrossAssessment

    line = assessment_line()
    value = OriginalGrossAssessment(
        capture_id=U[19],
        event_id=U[20],
        payment_id=U[8],
        source_hash=HASH,
        lines=(line,),
    )
    assert value.lines[0].issuance_entry_id == U[12]
    assert value.available is True
    absent = assessment_line(
        status="covered_absence",
        snapshot_id=None,
        potential_id=U[21],
        obligation_id=None,
        issuance_entry_id=None,
        recipient_id=None,
        frozen_rate_bps=None,
        liability_minor=0,
        unavailable_reason=None,
    )
    unresolved = replace(
        absent,
        status="unavailable",
        potential_id=None,
        liability_minor=None,
        unavailable_reason="original_history_unavailable",
    )
    assert replace(value, lines=(absent,)).available is True
    assert replace(value, lines=(unresolved,)).available is False
    assert unresolved.liability_minor is None
    for changes in (
        {"lines": ()},
        {"lines": [line]},
        {"lines": (line, line)},
        {"capture_id": "forged"},
        {"source_hash": "bad"},
    ):
        with pytest.raises(ValueError):
            replace(value, **changes)
    for source, changes in (
        (line, {"issuance_entry_id": None}),
        (line, {"potential_id": U[21]}),
        (line, {"liability_minor": 4999}),
        (line, {"frozen_rate_bps": True}),
        (line, {"status": "fake"}),
        (absent, {"potential_id": None}),
        (absent, {"recipient_id": U[13]}),
        (absent, {"liability_minor": 1}),
        (unresolved, {"unavailable_reason": None}),
        (unresolved, {"liability_minor": 0}),
    ):
        with pytest.raises(ValueError):
            replace(source, **changes)


def test_physical_identity_is_unambiguous_and_owner_requires_trusted_ids():
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofIdentity,
        PhysicalProofOwner,
    )

    first = PhysicalProofIdentity(
        source="a:b", account="c", direction="outgoing", reference="d"
    )
    second = PhysicalProofIdentity(
        source="a", account="b:c", direction="outgoing", reference="d"
    )
    assert first.key != second.key
    assert first.key == '["a:b","c","outgoing","d"]'
    owner = PhysicalProofOwner(
        producer="refund",
        intent_id=U[22],
        observation_id=U[23],
        command_id=U[24],
    )
    assert owner.intent_id == U[22]
    for changes in (
        {"source": " "},
        {"account": "x" * 257},
        {"direction": "sideways"},
        {"reference": 1},
    ):
        with pytest.raises(ValueError):
            replace(first, **changes)
    for changes in (
        {"producer": "fake"},
        {"intent_id": None},
        {"observation_id": "forged"},
        {"command_id": UUID(int=0)},
    ):
        with pytest.raises(ValueError):
            replace(owner, **changes)


def test_scope_distinguishes_missing_capture_and_complete_sorted_barriers():
    from ugc_bot.application.correction_ports import CorrectionScope
    from ugc_bot.domain.corrections import SelectionRefundBundle

    early = CorrectionScope(
        actor_id=U[0],
        prospective_user_ids=(U[1], U[0]),
        wallet_user_ids=(),
        source_hash=None,
        unavailable_reason="capture_missing",
    )
    assert early.prospective_user_ids == (U[0], U[1])
    assert early.capture_id is None
    assert early.available is False
    actual = replace(
        early,
        source_hash=HASH,
        order_id=U[1],
        client_id=U[1],
        intent_id=U[2],
        capture_id=U[3],
        payment_id=U[8],
        captured_at=NOW,
        quote_key="quote:actual",
        terms_reference="terms:actual",
        bundle=SelectionRefundBundle(components=(component(),)),
        unavailable_reason=None,
    )
    assert actual.available is True
    assert actual.captured_at.tzinfo is timezone.utc
    for changes in (
        {"prospective_user_ids": (U[1],)},
        {"wallet_user_ids": (U[9],)},
        {"client_id": U[9]},
        {"source_hash": None},
        {"captured_at": None},
        {"captured_at": datetime(2026, 1, 1)},
        {"quote_key": " "},
        {"order_id": "fake"},
        {"bundle": {}},
        {"payment_id": U[7]},
    ):
        with pytest.raises(ValueError):
            replace(actual, **changes)


def test_missing_account_labels_and_original_reference_stay_manual_facts():
    from ugc_bot.application.correction_ports import (
        RecordManualRefundObservation,
    )

    value = RecordManualRefundObservation(
        **command_values(),
        case_id=None,
        known_order_id=None,
        known_capture_intent_id=None,
        original_payment_reference="",
        bank_account_label="",
        bank_reference="actual-bank-reference",
        amount_minor=None,
        currency=None,
        occurred_at=None,
        reported_component="unknown",
        evidence_reference="protected:bank-1",
        evidence_hash=HASH,
        expected_version=None,
    )
    assert value.original_payment_reference == ""
    assert value.bank_account_label == ""
    assert value.known_order_id is None
    with pytest.raises(ValueError):
        replace(value, bank_account_label=1)


@pytest.mark.parametrize(
    "amount,currency",
    [(50_000, "USD"), (-50_000, "unknown"), (0, ""), (-(2**63), None)],
)
def test_unsupported_actual_money_is_retained_without_positive_funding(
    amount, currency
):
    from ugc_bot.application.correction_ports import (
        RecordManualRefundObservation,
    )

    value = RecordManualRefundObservation(
        **command_values(),
        case_id=None,
        known_order_id=None,
        known_capture_intent_id=None,
        original_payment_reference="actual-original",
        bank_account_label="operator-label",
        bank_reference="actual-bank-reference",
        amount_minor=amount,
        currency=currency,
        occurred_at=NOW,
        reported_component="management",
        evidence_reference="protected:bank-2",
        evidence_hash=HASH,
        expected_version=None,
    )
    assert value.amount_minor == amount
    assert value.currency == currency
    assert value.reported_component == "management"
    assert value.provenance == "manual_admin_observation"


def test_canonical_hash_and_replay_reject_aliased_payloads_and_unknown_events():
    from ugc_bot.application.correction_ports import correction_command_hash
    from ugc_bot.domain.corrections import (
        correction_payload_hash,
        replay_correction_events,
    )

    with pytest.raises(ValueError):
        correction_payload_hash({"mutable": [1]})
    with pytest.raises(ValueError):
        correction_command_hash(object())
    with pytest.raises(ValueError):
        replay_correction_events((object(),))
    with pytest.raises(ValueError):
        state(blockers=("same", "same"))
    with pytest.raises(ValueError):
        assessment_line(unavailable_reason="unavailable")


def test_scope_freezes_case_and_selected_routing_before_capture():
    from ugc_bot.application.correction_ports import CorrectionScope

    scope = CorrectionScope(
        actor_id=U[0],
        prospective_user_ids=(U[0],),
        wallet_user_ids=(),
        source_hash=None,
        unavailable_reason="capture_missing",
        case_id=U[4],
        selected_paid_item_ids=(U[3], U[2]),
    )
    assert scope.case_id == U[4]
    assert scope.selected_paid_item_ids == (U[2], U[3])
    assert scope.capture_id is None and scope.bundle is None
    for changes in (
        {"case_id": "fake"},
        {"case_id": UUID(int=0)},
        {"selected_paid_item_ids": [U[2]]},
        {"selected_paid_item_ids": (U[2], U[2])},
        {"selected_paid_item_ids": (UUID(int=0),)},
        {"selected_paid_item_ids": tuple(UUID(int=i + 1) for i in range(31))},
    ):
        with pytest.raises(ValueError):
            replace(scope, **changes)


def test_server_fact_records_copy_nested_values_and_refuse_ambiguous_lookup():
    from ugc_bot.application.correction_ports import (
        CorrectionFact,
        CorrectionFacts,
    )

    source = {"case_id": U[4], "bundle": [{"minor": 50000}]}
    record = CorrectionFact.from_values("requests", source)
    source["bundle"][0]["minor"] = 1
    facts = CorrectionFacts(records=(record,))
    read = facts.one("requests", "case_id", U[4])
    read["bundle"][0]["minor"] = 2
    assert facts.rows("requests")[0]["bundle"] == [{"minor": 50000}]
    with pytest.raises(FrozenInstanceError):
        record.payload_json = "{}"
    with pytest.raises(ValueError, match="correction_fact_unavailable"):
        facts.one("intents")
    with pytest.raises(ValueError, match="correction_fact_unavailable"):
        CorrectionFacts(records=(record, record)).one("requests")
    for records in ([record], (object(),)):
        with pytest.raises(ValueError, match="correction_fact_invalid"):
            CorrectionFacts(records=records)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "caller_authority"},
        {"payload_json": None},
        {"payload_json": " " * 262145},
        {"payload_json": "[]"},
        {"payload_json": '{"b":2, "a":1}'},
        {"payload_json": '{"amount":NaN}'},
        {"payload_json": "{"},
    ],
)
def test_server_fact_records_reject_noncanonical_or_unbounded_json(changes):
    from ugc_bot.application.correction_ports import CorrectionFact

    with pytest.raises(ValueError):
        CorrectionFact(**(dict(kind="cases", payload_json="{}") | changes))


def test_actor_record_validates_current_native_and_role_facts():
    from ugc_bot.application.correction_ports import CorrectionActor

    actor = CorrectionActor(
        user_id=U[0],
        telegram_id="101",
        max_id=None,
        status="active",
        admin=True,
    )
    assert actor.telegram_id == "101" and actor.admin
    with pytest.raises(FrozenInstanceError):
        actor.status = "pause"
    for changes in (
        {"user_id": UUID(int=0)},
        {"status": " "},
        {"admin": 1},
        {"telegram_id": 101},
        {"max_id": "x" * 129},
    ):
        with pytest.raises(ValueError):
            replace(actor, **changes)


def test_receipt_identity_keeps_existing_convention_outside_economic_hash():
    from uuid import NAMESPACE_URL, uuid5

    from ugc_bot.application.correction_ports import (
        correction_command_hash,
        correction_command_id,
    )

    command = request(operation_key="refund:☃")
    expected = uuid5(NAMESPACE_URL, f"ugc:correction:{U[0]}:8:refund:☃")
    assert correction_command_id(command) == expected
    changed = replace(command, reason="Different economic receipt payload")
    assert correction_command_id(changed) == expected
    assert correction_command_hash(command) != correction_command_hash(changed)


def test_read_authority_contains_only_immutable_owner_and_action_facts():
    from ugc_bot.application.correction_ports import CorrectionReadAuthority

    absent = CorrectionReadAuthority(current_client_id=None)
    assert absent.action is None
    route = CorrectionReadAuthority(
        case_client_id=U[0],
        case_order_id=U[3],
        request_client_id=U[0],
        request_order_id=U[3],
        current_client_id=U[1],
        action="RequestSelectionRefund",
    )
    assert set(asdict(route)) == {
        "case_client_id",
        "case_order_id",
        "request_client_id",
        "request_order_id",
        "current_client_id",
        "action",
    }
    assert route.case_client_id != route.current_client_id
    with pytest.raises(FrozenInstanceError):
        route.action = "ReviewSelectionRefund"
    for changes in (
        {"case_client_id": str(U[0])},
        {"case_order_id": UUID(int=0)},
        {"request_client_id": str(U[0])},
        {"request_order_id": UUID(int=0)},
        {"current_client_id": UUID(int=0)},
        {"action": " "},
        {"action": "x" * 65},
    ):
        with pytest.raises(ValueError):
            replace(route, **changes)
