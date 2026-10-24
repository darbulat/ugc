"""Authenticated payout commands; public callers never supply journal proof."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.payout_contract_ports import (
    PayoutFieldDefinition,
    TermsDocumentInput,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PublishPayoutRequirements:
    actor_id: UUID
    operation_key: str
    reason: str
    expected_version: int
    effective_from: datetime
    legal_reference: str
    terms_reference: str
    evidence_reference: str
    required_fields: tuple[str, ...]
    enabled: bool = True
    document: TermsDocumentInput | None = None
    field_definitions: tuple[PayoutFieldDefinition, ...] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StorePayoutRequisites:
    actor_id: UUID
    operation_key: str
    requirements_id: UUID
    accepted_terms_reference: str
    details: dict[str, str]
    accepted_document_id: UUID | None = None
    accepted_document_hash: str | None = None
    accepted: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestPayout:
    actor_id: UUID
    operation_key: str
    requisites_id: UUID
    amount_minor: int
    currency: str = "RUB"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewPayout:
    actor_id: UUID
    operation_key: str
    request_id: UUID
    expected_version: int
    action: Literal["review", "reject", "start", "escalate"]
    reason: str
    evidence_reference: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordPayoutResult:
    actor_id: UUID
    operation_key: str
    request_id: UUID
    execution_id: UUID
    fence: UUID
    expected_version: int
    status: Literal["paid", "failed", "unknown"]
    reason: str
    evidence_reference: str
    evidence_hash: str
    bank_account: str = ""
    bank_reference: str = ""
    amount_minor: int | None = None
    currency: str | None = None
    settled_at: datetime | None = None
    recipient_details: dict[str, str] = field(default_factory=dict)


PayoutCommand = (
    PublishPayoutRequirements
    | StorePayoutRequisites
    | RequestPayout
    | ReviewPayout
    | RecordPayoutResult
)


def payout_payload_hash(payload):
    return hashlib.sha256(
        json.dumps(
            canonical(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class PayoutApplicationRefused(ValueError):
    """Money rolled back; the actual bank observation is still recorded."""
