"""Silence and delivery failures do not establish successful collaboration."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
DUE = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def assigned():
    from ugc_bot.domain.collaboration import Collaboration

    return Collaboration(
        assignment_id=uuid4(),
        client_id=uuid4(),
        creator_id=uuid4(),
        manager_id=uuid4(),
        due_at=DUE,
        agreed_at=NOW,
    )


def working():
    value = assigned()
    return value.start(actor_id=value.client_id, at=NOW)


def claimed():
    value = working()
    return value.claim_success(
        actor_id=value.creator_id, evidence="https://example.test/post", at=NOW
    )


def test_two_silent_parties_expire_without_success_or_release():
    value = working()
    before = value.advance(
        at=datetime(2026, 11, 8, 11, 59, 59, tzinfo=timezone.utc)
    )
    assert before.state == "in_progress"
    expired = before.advance(at=datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
    assert expired.state == "unconfirmed_expired"
    assert expired.success_final_at is None
    assert expired.available_at is None


def test_first_claim_opens_72_hours_without_releasing_any_money():
    value = claimed()
    assert value.state == "success_claimed"
    assert value.objection_deadline == datetime(
        2026, 10, 26, 12, tzinfo=timezone.utc
    )
    assert value.claimant_id == value.creator_id
    assert value.evidence == "https://example.test/post"
    assert value.success_final_at is None
    assert value.available_at is None


def test_dispute_on_71st_hour_blocks_timeout_success():
    value = claimed().record_notice(
        accepted=True, at=NOW + timedelta(seconds=1)
    )
    disputed = value.dispute(
        actor_id=value.client_id,
        reason="The published material does not match the brief",
        at=NOW + timedelta(hours=71),
    )
    assert disputed.state == "disputed"
    assert (
        disputed.dispute_reason
        == "The published material does not match the brief"
    )
    assert disputed.advance(at=NOW + timedelta(days=40)).state == "disputed"
    assert disputed.available_at is None


def test_timeout_finalizes_at_72_hours_and_starts_separate_14_day_hold():
    value = claimed().record_notice(
        accepted=True, at=NOW + timedelta(seconds=1)
    )
    assert (
        value.advance(at=NOW + timedelta(hours=71)).state == "success_claimed"
    )
    final = value.advance(at=datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
    assert final.state == "success_final"
    assert final.success_final_at == datetime(
        2026, 10, 26, 12, tzinfo=timezone.utc
    )
    assert final.available_at == datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
    assert (
        final.advance(
            at=datetime(2026, 11, 9, 11, 59, 59, tzinfo=timezone.utc)
        ).state
        == "success_final"
    )
    assert (
        final.advance(at=datetime(2026, 11, 9, 12, tzinfo=timezone.utc)).state
        == "available"
    )


@pytest.mark.parametrize("notice", [None, False])
def test_missing_or_failed_notice_never_autofinalizes(notice):
    value = claimed()
    if notice is not None:
        value = value.record_notice(
            accepted=notice, at=NOW + timedelta(seconds=1)
        )
    later = value.advance(at=NOW + timedelta(days=40))
    assert later.state == "success_claimed"
    assert later.success_final_at is None
    assert later.available_at is None


def test_notice_retry_does_not_erase_failure_or_restart_objection_window():
    value = claimed()
    failed = value.record_notice(accepted=False, at=NOW + timedelta(seconds=1))
    retried = failed.record_notice(accepted=True, at=NOW + timedelta(hours=2))
    assert retried.notice_failed_at == NOW + timedelta(seconds=1)
    assert retried.objection_deadline == NOW + timedelta(hours=72)
    assert (
        retried.advance(at=NOW + timedelta(days=4)).state == "success_claimed"
    )


def test_explicit_opposite_party_agreement_can_finalize_despite_failed_notice():
    value = claimed().record_notice(
        accepted=False, at=NOW + timedelta(seconds=1)
    )
    final = value.agree(actor_id=value.client_id, at=NOW + timedelta(hours=1))
    assert final.state == "success_final"
    assert final.success_final_at == NOW + timedelta(hours=1)
    assert final.available_at == datetime(2026, 11, 6, 13, tzinfo=timezone.utc)


@pytest.mark.parametrize("command", ["agree", "dispute"])
def test_claimant_cannot_confirm_or_object_to_own_claim(command):
    value = claimed()
    kwargs = {"reason": "changed my mind"} if command == "dispute" else {}
    with pytest.raises(ValueError, match="opposite_party_required"):
        getattr(value, command)(
            actor_id=value.creator_id, at=NOW + timedelta(hours=1), **kwargs
        )


def test_manager_can_start_assigned_work_but_cannot_self_claim_reward():
    value = assigned()
    value = value.start(actor_id=value.manager_id, at=NOW)
    assert value.state == "in_progress"
    with pytest.raises(ValueError, match="collaboration_party_required"):
        value.claim_success(actor_id=value.manager_id, evidence="done", at=NOW)


def test_unknown_user_cannot_start_or_claim_collaboration():
    value = assigned()
    with pytest.raises(ValueError, match="assignment_actor_required"):
        value.start(actor_id=uuid4(), at=NOW)
    value = value.start(actor_id=value.client_id, at=NOW)
    with pytest.raises(ValueError, match="collaboration_party_required"):
        value.claim_success(actor_id=uuid4(), evidence="done", at=NOW)


def test_claim_needs_evidence_and_dispute_needs_reason():
    value = working()
    with pytest.raises(ValueError, match="evidence_required"):
        value.claim_success(actor_id=value.creator_id, evidence="  ", at=NOW)
    value = value.claim_success(
        actor_id=value.creator_id, evidence="Uploaded material 42", at=NOW
    )
    with pytest.raises(ValueError, match="dispute_reason_required"):
        value.dispute(actor_id=value.client_id, reason=" ", at=NOW)


def test_claim_window_boundary_never_resurrects_expired_work():
    value = working()
    boundary = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    valid = value.claim_success(
        actor_id=value.creator_id,
        evidence="done",
        at=boundary - timedelta(microseconds=1),
    )
    assert valid.state == "success_claimed"
    with pytest.raises(ValueError, match="claim_window_closed"):
        value.claim_success(
            actor_id=value.creator_id, evidence="done", at=boundary
        )
    with pytest.raises(ValueError, match="collaboration_state_conflict"):
        value.advance(at=boundary).claim_success(
            actor_id=value.creator_id, evidence="done", at=boundary
        )


def test_late_first_claim_retains_full_objection_window_after_due_plus_14():
    value = working()
    at = datetime(2026, 11, 8, 11, tzinfo=timezone.utc)
    value = value.claim_success(
        actor_id=value.creator_id, evidence="done", at=at
    )
    assert value.advance(at=at + timedelta(hours=1)).state == "success_claimed"
    assert value.objection_deadline == datetime(
        2026, 11, 11, 11, tzinfo=timezone.utc
    )


def test_client_agreed_extension_is_versioned_without_resetting_first_claim():
    value = claimed()
    extended = value.extend_due(
        actor_id=value.client_id,
        due_at=DUE + timedelta(days=3),
        expected_due_version=1,
        at=NOW + timedelta(hours=1),
    )
    assert extended.due_version == 2
    assert extended.due_at == datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert extended.claimed_at == NOW
    assert extended.objection_deadline == NOW + timedelta(hours=72)
    with pytest.raises(ValueError, match="due_version_conflict"):
        extended.extend_due(
            actor_id=value.client_id,
            due_at=DUE + timedelta(days=5),
            expected_due_version=1,
            at=NOW + timedelta(hours=2),
        )


def test_creator_cannot_extend_due_without_client_consent():
    value = working()
    with pytest.raises(ValueError, match="client_consent_required"):
        value.extend_due(
            actor_id=value.creator_id,
            due_at=DUE + timedelta(days=2),
            expected_due_version=1,
            at=NOW,
        )


def test_second_claim_does_not_replace_first_timestamp_or_evidence():
    value = claimed()
    with pytest.raises(ValueError, match="collaboration_state_conflict"):
        value.claim_success(
            actor_id=value.client_id,
            evidence="other",
            at=NOW + timedelta(hours=2),
        )
    assert value.claimed_at == NOW
    assert value.evidence == "https://example.test/post"


def test_objection_window_is_closed_exactly_at_72_hours():
    value = claimed()
    with pytest.raises(ValueError, match="objection_window_closed"):
        value.dispute(
            actor_id=value.client_id,
            reason="late",
            at=NOW + timedelta(hours=72),
        )


@pytest.mark.parametrize(
    "method",
    [
        "advance",
        "claim_success",
        "agree",
        "dispute",
        "record_notice",
        "extend_due",
    ],
)
def test_naive_timestamps_never_get_server_timezone(method):
    value = (
        claimed()
        if method in ("agree", "dispute", "record_notice", "extend_due")
        else working()
    )
    args = {
        "claim_success": {"actor_id": value.creator_id, "evidence": "done"},
        "agree": {"actor_id": value.client_id},
        "dispute": {"actor_id": value.client_id, "reason": "bad"},
        "record_notice": {"accepted": True},
        "extend_due": {
            "actor_id": value.client_id,
            "due_at": DUE + timedelta(days=1),
            "expected_due_version": 1,
        },
    }.get(method, {})
    with pytest.raises(ValueError, match="aware_timestamp_required"):
        getattr(value, method)(at=NOW.replace(tzinfo=None), **args)


def test_event_before_agreement_is_rejected_and_due_is_required():
    value = assigned()
    with pytest.raises(ValueError, match="collaboration_time_conflict"):
        value.start(actor_id=value.client_id, at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="agreed_due_at_required"):
        replace(value, due_at=NOW - timedelta(seconds=1))
