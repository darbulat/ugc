"""Visibly synthetic readable test input, never production legal content."""

from dataclasses import asdict
from uuid import UUID

from ugc_bot.application.payout_contract_ports import (
    PayoutFieldDefinition,
    TermsDocumentInput,
)

FIELDS = ("recipient_name", "bank_account", "legal_status")


def publication_fields(fields=FIELDS):
    return dict(
        document=TermsDocumentInput(
            content_text=(
                "Synthetic payout document for automated contract tests only.\n"
                "This is not production legal approval."
            ),
            source_locale="en",
        ),
        field_definitions=tuple(
            PayoutFieldDefinition(
                key=key, labels={"en": "Synthetic " + key.replace("_", " ")}
            )
            for key in fields
        ),
    )


def publication_json(fields=FIELDS):
    values = publication_fields(fields)
    return dict(
        document=asdict(values["document"]),
        field_definitions=[asdict(v) for v in values["field_definitions"]],
    )


def acceptance_fields(publication):
    document = publication["document"]
    return dict(
        accepted=True,
        accepted_document_id=UUID(str(document["document_id"])),
        accepted_document_hash=document["sha256"],
    )


def acceptance_json(publication):
    values = acceptance_fields(publication)
    return values | {
        "accepted_document_id": str(values["accepted_document_id"])
    }
