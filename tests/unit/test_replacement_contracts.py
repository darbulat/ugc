"""Strict internal commands cannot smuggle ambiguous versions or authority."""

from dataclasses import replace
from uuid import UUID

import pytest

from tests.application.services.test_replacement_service import (
    ADMIN,
    CLIENT,
    INTEREST,
    ITEM,
    approve,
)
from ugc_bot.application.replacement_ports import (
    ReplacementContact,
    ReplacementRequest,
)


@pytest.mark.parametrize(
    "change",
    [
        dict(actor_id=UUID(int=0)),
        dict(paid_item_id="not-an-id"),
        dict(operation_key=""),
        dict(operation_key="x" * 257),
        dict(reason=" "),
        dict(evidence_reference="x" * 4001),
        dict(expected_assignment_version=True),
        dict(expected_assignment_version=0),
        dict(reason_code="other"),
    ],
)
def test_request_rejects_invalid_provenance_and_versions(change):
    command = ReplacementRequest(
        "request", CLIENT, ITEM, 1, INTEREST, "refusal", "Отказ", "support:1"
    )
    with pytest.raises(ValueError):
        replace(command, **change)


@pytest.mark.parametrize(
    "change",
    [
        dict(request_id=UUID(int=0)),
        dict(manager_id="invalid"),
        dict(expected_version=True),
        dict(action="other"),
        dict(exception_reason="review", exception_evidence=None),
        dict(exception_reason="review", exception_evidence=" "),
    ],
)
def test_decision_requires_strict_version_and_paired_exception_evidence(change):
    with pytest.raises(ValueError):
        replace(approve(str(ITEM)), **change)


def test_contact_identity_and_reason_are_required():
    with pytest.raises(ValueError):
        ReplacementContact(
            "contact", ADMIN, UUID(int=0), "Контакт", "miniapp:explicit"
        )
