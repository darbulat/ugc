"""Waiting explanations expose public identities only from one's own network."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from ugc_bot.infrastructure.db.repositories.partner_pending import (
    pending_context,
)

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
CLIENT, CREATOR = UUID(int=10), UUID(int=11)


def record(**changes):
    return {
        "state": "in_progress",
        "due_at": NOW,
        "client_id": CLIENT,
        "creator_id": CREATOR,
        "record_payload": {
            "evidence": "PRIVATE MATERIAL",
            "dispute_reason": "PRIVATE",
        },
    } | changes


def test_waiting_participants_only_name_members_owned_by_this_partner():
    result = pending_context(
        record(), NOW, {CREATOR: ("Creator", "creator_public")}
    )
    assert result.reason == "awaiting_confirmation"
    assert [
        (p.role, p.display_name, p.telegram_username)
        for p in result.waiting_for
    ] == [("client", None, None), ("creator", "Creator", "creator_public")]
    assert "PRIVATE" not in str(result)


def test_first_claim_names_only_the_counterparty_and_reports_notice_failure():
    result = pending_context(
        record(
            state="success_claimed",
            record_payload={
                "collaboration": {
                    "claimant_id": str(CLIENT),
                    "notice_failed_at": NOW.isoformat(),
                }
            },
        ),
        NOW,
        {},
    )
    assert result.reason == "confirmation_notice_pending"
    assert [p.role for p in result.waiting_for] == ["creator"]
    result = pending_context(
        record(
            state="success_claimed",
            record_payload={
                "collaboration": {
                    "claimant_id": str(CLIENT),
                    "notice_delivered_at": NOW.isoformat(),
                }
            },
        ),
        NOW,
        {},
    )
    assert result.reason == "awaiting_counterparty"


def test_expired_pending_is_explained_without_fabricating_a_ledger_reversal():
    result = pending_context(record(due_at=NOW - timedelta(days=14)), NOW, {})
    assert result.reason == "expiry_processing"
    assert result.waiting_for == ()


def test_final_success_has_no_unconfirmed_party():
    result = pending_context(record(state="success_final"), NOW, {})
    assert result.reason == "financial_processing"
    assert result.waiting_for == ()


def test_disputed_expired_and_malformed_sources_do_not_expose_evidence():
    assert (
        pending_context(record(state="disputed"), NOW, {}).reason
        == "dispute_review"
    )
    assert (
        pending_context(record(state="unconfirmed_expired"), NOW, {}).reason
        == "expiry_processing"
    )
    result = pending_context(
        record(record_payload="PRIVATE RAW PAYLOAD"), NOW, {}
    )
    assert result.reason == "awaiting_confirmation" and "PRIVATE" not in str(
        result
    )
