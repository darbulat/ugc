"""Retained immutable command identities survive added contract proof."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from uuid import uuid4

from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    StorePayoutRequisites,
)


def payload(command):
    from ugc_bot.application.payout_contracts import command_payload

    return command_payload(command)


def publication():
    return PublishPayoutRequirements(
        actor_id=uuid4(),
        operation_key="old-publication",
        reason="Synthetic",
        expected_version=0,
        effective_from=datetime.now(timezone.utc),
        legal_reference="synthetic:old",
        terms_reference="opaque:old",
        evidence_reference="synthetic:old-proof",
        required_fields=("recipient_name", "bank_account", "legal_status"),
    )


def test_new_optional_defaults_preserve_exact_old_publication_hash_shape():
    command = publication()
    old = {
        k: v
        for k, v in asdict(command).items()
        if k not in ("document", "field_definitions")
    }
    assert payload(command) == old
    assert payload(replace(command, enabled=False)) == old | {"enabled": False}


def test_new_optional_defaults_preserve_exact_old_secret_command_shape():
    command = StorePayoutRequisites(
        actor_id=uuid4(),
        operation_key="old-requisites",
        requirements_id=uuid4(),
        accepted_terms_reference="opaque:old",
        details={"bank_account": "001"},
    )
    old = {
        k: v
        for k, v in asdict(command).items()
        if k
        not in ("accepted_document_id", "accepted_document_hash", "accepted")
    }
    assert payload(command) == old
    assert payload(replace(command, accepted=False))["accepted"] is False


def test_masked_receipt_preserves_any_existing_four_character_suffix():
    from ugc_bot.application.payout_contracts import owner_receipt

    result = dict(
        requisites_id=str(uuid4()),
        requirements_id=str(uuid4()),
        masked_label="••••a\nbc",
        recipient_details={"secret": "never-return"},
    )
    safe = owner_receipt("StorePayoutRequisites", result)
    assert safe["masked_label"] == result["masked_label"]
    assert "recipient_details" not in safe
