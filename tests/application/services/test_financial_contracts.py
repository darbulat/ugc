from datetime import datetime, timezone
from uuid import uuid4

import pytest


def movement(**changes):
    from ugc_bot.application.financial_ports import JournalMovement

    data = dict(
        obligation_id=uuid4(),
        operation_key="reserve-1",
        event_id="event-1",
        movement_type="transfer",
        amount_minor=100,
        currency="RUB",
        effective_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
        actor_id=uuid4(),
        reason="reserve",
    )
    data.update(changes)
    return JournalMovement(**data)


def test_journal_contract_rejects_ambiguous_movement():
    with pytest.raises(ValueError, match="transfer_buckets_required"):
        movement()


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"movement_type": "reversal"}, "correction_source_required"),
        (
            {"movement_type": "recovery", "source_entry_id": uuid4()},
            "recovery_case_required",
        ),
        ({"movement_type": "mystery"}, "invalid_movement_type"),
        (
            {"bucket_from": "available", "bucket_to": "paid"},
            "paid_execution_required",
        ),
        (
            {"movement_type": "issuance", "bucket_to": "paid"},
            "issuance_pending_required",
        ),
        (
            {"bucket_from": "paid", "bucket_to": "available"},
            "historical_paid_immutable",
        ),
        (
            {"bucket_from": "available", "bucket_to": "mystery"},
            "invalid_bucket",
        ),
    ],
)
def test_journal_rejects_unreplayable_economics(changes, error):
    with pytest.raises(ValueError, match=error):
        movement(**changes)


def test_reservation_requires_replayable_request_allocation():
    with pytest.raises(ValueError, match="reservation_references_required"):
        movement(bucket_from="available", bucket_to="reserved")


@pytest.mark.parametrize(
    "changes", [{"actor_id": None}, {"actor_id": "forged"}]
)
def test_journal_human_actor_is_not_optional_or_an_unchecked_string(changes):
    with pytest.raises(ValueError, match="journal_actor"):
        movement(bucket_from="hold", bucket_to="available", **changes)


def test_journal_normalizes_aware_instants_to_canonical_utc():
    from datetime import timedelta

    stamp = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=3)))
    entry = movement(
        bucket_from="hold",
        bucket_to="available",
        effective_at=stamp,
        recorded_at=stamp,
    )
    assert entry.effective_at.tzinfo is timezone.utc
    assert entry.recorded_at.tzinfo is timezone.utc


def test_journal_rejects_nonpersistable_bigint_amount():
    with pytest.raises(ValueError, match="minor_amount"):
        movement(bucket_from="hold", bucket_to="available", amount_minor=2**63)


@pytest.mark.parametrize(
    "source,target", [("cancelled", "available"), ("available", "cancelled")]
)
def test_transfer_cannot_create_or_reverse_an_economic_cancellation(
    source, target
):
    with pytest.raises(ValueError, match="economic_cancellation"):
        movement(bucket_from=source, bucket_to=target)


def test_system_event_has_named_provenance_without_a_fictitious_user_uuid():
    event = movement(
        bucket_from="hold",
        bucket_to="available",
        actor_kind="system",
        actor_id=None,
        system_actor="financial-availability-worker",
    )
    assert event.actor_id is None
    assert event.actor_kind == "system"
    assert event.system_actor == "financial-availability-worker"


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_kind": "system", "actor_id": None, "system_actor": " "},
        {
            "actor_kind": "system",
            "actor_id": uuid4(),
            "system_actor": "financial-worker",
        },
        {"actor_kind": "forged"},
        {"actor_kind": "user", "system_actor": "financial-worker"},
    ],
)
def test_journal_actor_provenance_cannot_be_ambiguous(changes):
    with pytest.raises(ValueError, match="journal_actor"):
        movement(bucket_from="hold", bucket_to="available", **changes)


@pytest.mark.parametrize("field", ["operation_key", "event_id", "reason"])
@pytest.mark.parametrize("value", [None, "", " ", 42])
def test_journal_metadata_cannot_be_an_unknown_or_implicitly_stringified_value(
    field, value
):
    with pytest.raises(ValueError, match="journal_provenance"):
        movement(bucket_from="hold", bucket_to="available", **{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "obligation_id",
        "source_entry_id",
        "request_id",
        "allocation_id",
        "execution_id",
        "refund_id",
        "case_id",
    ],
)
def test_journal_references_are_typed_not_unchecked_payload_strings(field):
    with pytest.raises(ValueError, match="journal_reference"):
        movement(bucket_from="hold", bucket_to="available", **{field: "forged"})


@pytest.mark.parametrize(
    "kind",
    [
        "issuance",
        "reversal",
        "debt",
        "recovery",
        "reserve",
        "consume",
        "normal",
    ],
)
def test_replayable_positive_economic_shapes_and_immutability(kind):
    from dataclasses import FrozenInstanceError

    common = dict(bucket_from="hold", bucket_to="available")
    if kind == "issuance":
        common.update(
            movement_type="issuance", bucket_from=None, bucket_to="pending"
        )
    elif kind in ("reversal", "debt", "recovery"):
        common.update(
            movement_type=kind,
            source_entry_id=uuid4(),
            case_id=uuid4(),
            bucket_from=None,
            bucket_to=None,
        )
    elif kind in ("reserve", "consume"):
        common.update(
            bucket_from="available" if kind == "reserve" else "reserved",
            bucket_to="reserved" if kind == "reserve" else "paid",
            request_id=uuid4(),
            allocation_id=uuid4(),
            execution_id=uuid4(),
        )
    event = movement(**common)
    assert event.amount_minor == 100
    with pytest.raises(FrozenInstanceError):
        event.amount_minor = 200


@pytest.mark.parametrize("amount", [0, -1, True, 1.0, "1", None])
def test_journal_minor_amount_is_positive_integer_not_coercion(amount):
    with pytest.raises(ValueError, match="minor_amount"):
        movement(bucket_from="hold", bucket_to="available", amount_minor=amount)
