"""Actual facts determine dates and cumulative targets, never money writes."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest

AT = datetime(2026, 10, 25, 10, tzinfo=timezone.utc)


def rules(**changes):
    try:
        contract = import_module("ugc_bot.domain.refund_rules").RefundRules
    except ModuleNotFoundError:
        pytest.fail("Immutable configurable refund rules are not implemented")
    fields = dict(
        selection_refund_window_seconds=86400,
        selection_refund_window_anchor="item_delivered",
        selection_closure_mode="all_positions_resolved",
        accompaniment_refund_rates_bps=(("in_progress", 2500),),
        accompaniment_manager_refund_mode="retain_earned",
    )
    fields.update(changes)
    return contract(**fields)


def document():
    return {
        "schema_version": 1,
        "selection_refund_window_seconds": 86400,
        "selection_refund_window_anchor": "item_delivered",
        "selection_closure_mode": "all_positions_resolved",
        "accompaniment_refund_rates_bps": {"in_progress": 2500},
        "accompaniment_manager_refund_mode": "retain_earned",
    }


def test_document_roundtrip_preserves_actual_configured_terms():
    selected = rules()
    assert selected.to_document() == document()
    assert type(selected).from_document(document()) == selected
    with pytest.raises(FrozenInstanceError):
        selected.selection_refund_window_seconds = 1


def test_automatic_closure_waits_for_every_actual_position_resolution():
    selected = rules()
    assert selected.selection_closed_at(position_resolved_at=(AT, None)) is None
    assert selected.selection_closed_at(
        position_resolved_at=(AT, AT + timedelta(days=2))
    ) == AT + timedelta(days=2)


def test_selection_availability_requires_order_closure_and_separate_hold():
    selected = rules()
    assert selected.selection_refund_deadline(
        item_delivered_at=AT, order_closed_at=None
    ) == AT + timedelta(days=1)
    assert (
        selected.selection_available_at(
            item_delivered_at=AT, order_closed_at=None
        )
        is None
    )
    assert selected.selection_available_at(
        item_delivered_at=AT, order_closed_at=AT + timedelta(days=3)
    ) == AT + timedelta(days=17)


def test_stage_rate_assesses_customer_without_reversing_earned():
    assessment = rules().assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=60000
    )
    assert assessment.customer_refund_minor == 30000
    assert assessment.manager_adjustment_minor == 0
    assert assessment.review_reason is None


@pytest.mark.parametrize(
    "changes",
    [
        {"selection_refund_window_seconds": value}
        for value in (True, 1.0, 0, -1, 31536001, "86400", None)
    ]
    + [
        {"selection_refund_window_anchor": value}
        for value in ("payment", "", None, [], 1)
    ]
    + [
        {"selection_closure_mode": value}
        for value in ("automatic", "", None, [], 1)
    ]
    + [
        {"accompaniment_manager_refund_mode": value}
        for value in ("subtract", "", None, [], 1)
    ]
    + [
        {"accompaniment_refund_rates_bps": value}
        for value in (
            {},
            [],
            (("unknown", 100),),
            (("disputed", 100),),
            (("in_progress", True),),
            (("in_progress", 1.0),),
            (("in_progress", -1),),
            (("in_progress", 10001),),
            (("in_progress", 1), ("in_progress", 2)),
            (("in_progress",),),
            (["in_progress", 100],),
            ((False, 100),),
        )
    ],
)
def test_invalid_rules_cannot_choose_financial_behavior(changes):
    with pytest.raises(ValueError):
        rules(**changes)


@pytest.mark.parametrize("seconds", (1, 31536000))
def test_window_bounds_are_inclusive(seconds):
    assert (
        rules(
            selection_refund_window_seconds=seconds
        ).selection_refund_window_seconds
        == seconds
    )


def test_stage_map_is_canonical_immutable_and_document_is_independent():
    selected = rules(
        accompaniment_refund_rates_bps=(
            ("success_final", 0),
            ("assigned", 10000),
        )
    )
    assert selected.accompaniment_refund_rates_bps == (
        ("assigned", 10000),
        ("success_final", 0),
    )
    saved = selected.to_document()
    saved["accompaniment_refund_rates_bps"]["assigned"] = 0
    assert dict(selected.accompaniment_refund_rates_bps)["assigned"] == 10000


@pytest.mark.parametrize(
    "value",
    [None, [], "{}", {}]
    + [dict(document(), schema_version=v) for v in (True, 1.0, 0, 2, "1")]
    + [dict(document(), extra="unknown")]
    + [dict(document(), accompaniment_refund_rates_bps=v) for v in ([], None)]
    + [dict(document(), selection_refund_window_seconds=True)]
    + [{k: v for k, v in document().items() if k != "selection_closure_mode"}],
)
def test_unknown_or_malformed_document_is_not_accepted(value):
    with pytest.raises(ValueError):
        type(rules()).from_document(value)


def test_all_current_work_stages_except_disputed_can_be_configured():
    from ugc_bot.domain.collaboration import CollaborationState
    from ugc_bot.domain.refund_rules import ACCOMPANIMENT_REFUND_STAGES

    expected = {
        state.value
        for state in CollaborationState
        if state != CollaborationState.DISPUTED
    }
    assert expected == ACCOMPANIMENT_REFUND_STAGES
    selected = rules(
        accompaniment_refund_rates_bps=tuple(
            (stage, 0) for stage in ACCOMPANIMENT_REFUND_STAGES
        )
    )
    assert type(selected).from_document(selected.to_document()) == selected


def test_manual_closure_requires_actual_resolution_and_explicit_closure_fact():
    selected = rules(selection_closure_mode="manual")
    assert selected.selection_closed_at(position_resolved_at=(AT,)) is None
    assert (
        selected.selection_closed_at(
            position_resolved_at=(AT, None), manual_closed_at=AT
        )
        is None
    )
    assert selected.selection_closed_at(
        position_resolved_at=(AT,), manual_closed_at=AT + timedelta(hours=1)
    ) == AT + timedelta(hours=1)


@pytest.mark.parametrize("values", ((), [], ("2026-10-25",)))
def test_closure_rejects_absent_or_invalid_positional_facts(values):
    with pytest.raises(ValueError):
        rules().selection_closed_at(position_resolved_at=values)


def test_automatic_closure_cannot_be_overridden_by_a_manual_fact():
    with pytest.raises(ValueError, match="not_applicable"):
        rules().selection_closed_at(
            position_resolved_at=(AT,), manual_closed_at=AT
        )


def test_manual_closure_cannot_precede_resolution():
    with pytest.raises(ValueError, match="before_resolution"):
        rules(selection_closure_mode="manual").selection_closed_at(
            position_resolved_at=(AT,),
            manual_closed_at=AT - timedelta(seconds=1),
        )


def test_order_closed_anchor_uses_actual_closure_then_window_then_hold():
    selected = rules(selection_refund_window_anchor="order_closed")
    assert (
        selected.selection_refund_deadline(
            item_delivered_at=AT, order_closed_at=None
        )
        is None
    )
    assert selected.selection_available_at(
        item_delivered_at=AT, order_closed_at=AT + timedelta(days=3)
    ) == AT + timedelta(days=18)


def test_item_anchor_refuses_missing_delivery_and_keeps_hold_after_window():
    selected = rules()
    assert (
        selected.selection_refund_deadline(
            item_delivered_at=None, order_closed_at=AT
        )
        is None
    )
    assert (
        selected.selection_available_at(
            item_delivered_at=None, order_closed_at=AT
        )
        is None
    )
    assert selected.selection_available_at(
        item_delivered_at=AT, order_closed_at=AT
    ) == AT + timedelta(days=15)


def test_actual_delivery_after_order_closure_is_inconsistent():
    with pytest.raises(ValueError, match="before_delivery"):
        rules().selection_refund_deadline(
            item_delivered_at=AT, order_closed_at=AT - timedelta(seconds=1)
        )


@pytest.mark.parametrize("invalid", (AT.replace(tzinfo=None), "now", True))
def test_date_calculations_reject_naive_or_untyped_times(invalid):
    with pytest.raises(ValueError):
        rules().selection_closed_at(position_resolved_at=(invalid,))
    with pytest.raises(ValueError):
        rules().selection_refund_deadline(
            item_delivered_at=invalid, order_closed_at=None
        )
    with pytest.raises(ValueError):
        rules().selection_available_at(
            item_delivered_at=AT, order_closed_at=invalid
        )


def test_date_calculations_normalize_real_aware_timestamps_to_utc():
    offset = AT.astimezone(timezone(timedelta(hours=3)))
    assert rules().selection_closed_at(position_resolved_at=(offset,)) == AT
    assert rules().selection_available_at(
        item_delivered_at=offset, order_closed_at=offset
    ) == AT + timedelta(days=15)


def test_datetime_overflow_cannot_produce_an_eligible_date():
    end = datetime.max.replace(tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="out_of_range"):
        rules().selection_refund_deadline(
            item_delivered_at=end, order_closed_at=end
        )
    with pytest.raises(ValueError, match="out_of_range"):
        rules().selection_available_at(
            item_delivered_at=end - timedelta(days=2), order_closed_at=end
        )


@pytest.mark.parametrize("stage", ("disputed", "success_final", "assigned"))
def test_disputed_or_unconfigured_stage_requires_explicit_review(stage):
    result = rules().assess_accompaniment_refund(
        stage=stage, paid_minor=120000, manager_earned_minor=60000
    )
    assert result.customer_refund_minor is None
    assert result.manager_adjustment_minor is None
    assert result.review_reason == "accompaniment_refund_review_required"


@pytest.mark.parametrize("stage", ("unknown", "", None, [], True))
def test_unknown_stage_is_invalid_not_a_configurable_default(stage):
    with pytest.raises(ValueError):
        rules().assess_accompaniment_refund(
            stage=stage, paid_minor=120000, manager_earned_minor=0
        )


def test_empty_stage_map_never_invents_a_refund_percentage():
    result = rules(
        accompaniment_refund_rates_bps=()
    ).assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=0
    )
    assert result.customer_refund_minor is None
    assert result.review_reason


@pytest.mark.parametrize("rate", (0, 1, 3333, 5000, 10000))
@pytest.mark.parametrize("earned", (0, 60000))
def test_proportional_assessment_is_a_repeatable_cumulative_target(
    rate, earned
):
    selected = rules(
        accompaniment_refund_rates_bps=(("in_progress", rate),),
        accompaniment_manager_refund_mode="proportional",
    )
    first = selected.assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=earned
    )
    repeat = selected.assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=earned
    )
    assert first == repeat
    assert first.customer_refund_minor == 12 * rate
    assert first.manager_adjustment_minor == earned // 10000 * rate
    assert first.review_reason is None


def test_manual_manager_mode_keeps_known_customer_target_but_requires_review():
    result = rules(
        accompaniment_manager_refund_mode="manual_review"
    ).assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=60000
    )
    assert result.customer_refund_minor == 30000
    assert result.manager_adjustment_minor is None
    assert result.review_reason == "manager_adjustment_review_required"


@pytest.mark.parametrize("rate,earned", ((2500, 0), (0, 60000), (0, 0)))
def test_manual_manager_mode_needs_no_review_when_no_adjustment_is_possible(
    rate, earned
):
    result = rules(
        accompaniment_manager_refund_mode="manual_review",
        accompaniment_refund_rates_bps=(("in_progress", rate),),
    ).assess_accompaniment_refund(
        stage="in_progress", paid_minor=120000, manager_earned_minor=earned
    )
    assert result.customer_refund_minor == 12 * rate
    assert result.manager_adjustment_minor == 0
    assert result.review_reason is None


def test_order_closed_anchor_does_not_make_undelivered_item_available():
    selected = rules(selection_refund_window_anchor="order_closed")
    assert selected.selection_refund_deadline(
        item_delivered_at=None, order_closed_at=AT
    ) == AT + timedelta(days=1)
    assert (
        selected.selection_available_at(
            item_delivered_at=None, order_closed_at=AT
        )
        is None
    )


def test_zero_funded_component_and_no_earned_reward_have_zero_target():
    result = rules().assess_accompaniment_refund(
        stage="in_progress", paid_minor=0, manager_earned_minor=0
    )
    assert result.customer_refund_minor == result.manager_adjustment_minor == 0


@pytest.mark.parametrize(
    "changes",
    [{"paid_minor": v} for v in (True, 1.0, -1, 1, 119999, 120001)]
    + [{"manager_earned_minor": v} for v in (True, 1.0, -1, 1, 59999, 60001)]
    + [{"paid_minor": 0, "manager_earned_minor": 60000}],
)
def test_assessment_rejects_invalid_or_unapproved_standard_money(changes):
    arguments = dict(
        stage="in_progress", paid_minor=120000, manager_earned_minor=60000
    )
    arguments.update(changes)
    with pytest.raises(ValueError):
        rules().assess_accompaniment_refund(**arguments)
