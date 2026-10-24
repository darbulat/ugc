"""Unreadable sources and unsafe receipt payloads are unavailable."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.payout_contract_ports import (
    PayoutFieldDefinition,
    TermsDocumentInput,
)
from ugc_bot.application.payout_contracts import (
    document_hash,
    document_input,
    field_definitions,
    owner_receipt,
    require_acceptance,
)
from ugc_bot.domain.financial import MAX_MINOR


@pytest.mark.parametrize("value", [None, 7, "", " \n", "x" * 1000001])
def test_missing_or_excessive_actual_source_is_rejected(value):
    with pytest.raises(ValueError, match="payout_readable_terms_required"):
        document_hash(value)


@pytest.mark.parametrize(
    "source",
    [
        None,
        {},
        TermsDocumentInput(document_id=UUID(int=0)),
        TermsDocumentInput(document_id="wrong"),
        TermsDocumentInput(document_id=uuid4(), content_text="extra"),
        TermsDocumentInput(content_text="actual", source_locale=""),
        TermsDocumentInput(content_text="actual", source_locale="1x"),
    ],
)
def test_document_source_has_exactly_one_authority(source):
    with pytest.raises(ValueError, match="payout_"):
        document_input(source)


@pytest.mark.parametrize(
    "definition",
    [
        None,
        PayoutFieldDefinition(key="other", labels={"en": "Name"}),
        PayoutFieldDefinition(key="name", labels=[]),
        PayoutFieldDefinition(key="name", labels={"en": ""}),
        PayoutFieldDefinition(key="name", labels={"x": "Name"}),
        PayoutFieldDefinition(key="name", labels={"en": 4}),
        PayoutFieldDefinition(key="name", labels={"en": "x" * 2001}),
        PayoutFieldDefinition(key="name", labels={"ru": "Name"}),
        PayoutFieldDefinition(
            key="name", labels={"en": "Name"}, allowed_values=()
        ),
        PayoutFieldDefinition(
            key="name", labels={"en": "Name"}, allowed_values=("a", "a")
        ),
        PayoutFieldDefinition(
            key="name", labels={"en": "Name"}, allowed_values=("",)
        ),
        PayoutFieldDefinition(
            key="name", labels={"en": "Name"}, allowed_values=(3,)
        ),
        PayoutFieldDefinition(
            key="name", labels={"en": "Name"}, allowed_values=("a" * 2001,)
        ),
    ],
)
def test_invalid_field_metadata_never_invents_a_label_or_option(definition):
    with pytest.raises(ValueError, match="payout_field_definitions_invalid"):
        field_definitions([definition], ("name",), "en")


def test_exact_fields_and_source_locale_are_required():
    definition = PayoutFieldDefinition(
        key="name",
        labels={"en": "Name"},
        help={"ru": "Подсказка"},
        allowed_values=("actual",),
    )
    assert field_definitions([definition], ("name",), "en")[0]["help"] == {
        "ru": "Подсказка"
    }
    for values in (None, [], [definition, definition]):
        with pytest.raises(ValueError):
            field_definitions(values, ("name",), "en")
    with pytest.raises(ValueError):
        field_definitions([definition, definition], ("name", "other"), "en")
    with pytest.raises(ValueError, match="payout_readable_terms_required"):
        require_acceptance(None, None)


def receipt():
    return dict(
        request_id=str(uuid4()),
        requisites_id=str(uuid4()),
        requirements_id=str(uuid4()),
        amount_minor=MAX_MINOR,
        currency="RUB",
        requested_at=datetime.now(timezone.utc).isoformat(),
        deadline_at=datetime.now(timezone.utc).isoformat(),
        version=1,
        state="reserved",
        execution_id=None,
        block_reason="",
        masked_label="••••1234",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": True},
        {"amount_minor": 0},
        {"amount_minor": MAX_MINOR + 1},
        {"currency": "USD"},
        {"version": False},
        {"version": 0},
        {"state": "forged"},
        {"block_reason": {}},
        {"block_reason": "private details"},
        {"block_reason": "synthetic_private_details"},
        {"requested_at": "2026-01-01"},
        {"deadline_at": "invalid"},
        {"request_id": str(UUID(int=0))},
        {"execution_id": str(UUID(int=0))},
        {"masked_label": "unmasked-secret"},
        {"masked_label": 123},
        {"requirements_id": None},
    ],
)
def test_owner_lookup_fails_closed_for_corrupt_saved_receipt(change):
    with pytest.raises(ValueError, match="payout_operation_unavailable"):
        owner_receipt("RequestPayout", receipt() | change)


def test_receipt_whitelist_excludes_secrets_and_unsupported_commands():
    safe = owner_receipt(
        "RequestPayout",
        receipt()
        | {
            "fence": "secret",
            "details": {"bank_account": "secret"},
            "arbitrary_minor": 123,
        },
    )
    assert safe["amount_minor"] == MAX_MINOR and "fence" not in safe
    for action, value in (
        ("PublishPayoutRequirements", {}),
        ("StorePayoutRequisites", None),
        ("RequestPayout", {}),
    ):
        with pytest.raises(ValueError, match="payout_operation_unavailable"):
            owner_receipt(action, value)
    stored = dict(
        requisites_id=str(uuid4()),
        requirements_id=str(uuid4()),
        masked_label="••••",
        document_id=str(uuid4()),
        document_hash="a" * 64,
    )
    assert owner_receipt("StorePayoutRequisites", stored) == stored


def test_store_receipt_invalid_document_proof_is_unavailable():
    base = dict(requisites_id=str(uuid4()), requirements_id=str(uuid4()))
    with pytest.raises(ValueError, match="payout_operation_unavailable"):
        owner_receipt(
            "StorePayoutRequisites", base | {"document_hash": "invalid"}
        )


def test_existing_server_block_codes_remain_recoverable():
    from ugc_bot.application.payout_errors import PUBLIC_PAYOUT_BLOCK_CODES

    for code in PUBLIC_PAYOUT_BLOCK_CODES:
        original = receipt() | {"block_reason": code}
        assert owner_receipt("RequestPayout", original) == original


def test_actual_source_reference_and_explicit_proof_validation():
    from types import SimpleNamespace

    document_id = uuid4()
    source = document_input(
        TermsDocumentInput(
            content_text=" Synthetic source\n", source_locale="en"
        )
    )
    assert source["content_text"] == " Synthetic source\n"
    assert source["sha256"] == document_hash(source["content_text"])
    assert document_input(TermsDocumentInput(document_id=document_id)) == {
        "document_id": document_id
    }
    contract = dict(
        document=dict(document_id=document_id, sha256=source["sha256"]),
        field_definitions=[dict(key="status", allowed_values=["synthetic"])],
    )
    values = dict(
        accepted=True,
        accepted_document_id=document_id,
        accepted_document_hash=source["sha256"],
        details={"status": "synthetic"},
    )
    require_acceptance(SimpleNamespace(**values), contract)
    for change, code in (
        ({"accepted": False}, "payout_acceptance_required"),
        ({"accepted_document_id": uuid4()}, "payout_document_mismatch"),
        (
            {"details": {"status": "not-accepted"}},
            "payout_requisites_permitted_value_required",
        ),
    ):
        with pytest.raises(ValueError, match=code):
            require_acceptance(SimpleNamespace(**(values | change)), contract)
