"""Explicit reviews of already issued economic grounds, including paid ones."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ugc_bot.domain.corrections import (
    require_hash,
    require_minor,
    require_text,
    require_uuid,
    require_version,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenFinancialReview:
    actor_id: UUID
    operation_key: str
    business_key: str
    expected_source_hash: str
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        require_uuid(self.actor_id)
        for value in (
            self.operation_key,
            self.business_key,
            self.reason,
            self.evidence_reference,
        ):
            require_text(value)
        require_hash(self.expected_source_hash)
        require_hash(self.evidence_hash)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveFinancialReview:
    actor_id: UUID
    operation_key: str
    case_id: UUID
    expected_version: int
    expected_source_hash: str
    decision: Literal["no_adjustment", "cumulative_cancel"]
    target_minor: int | None
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        require_uuid(self.actor_id)
        require_uuid(self.case_id)
        require_version(self.expected_version)
        for value in (self.operation_key, self.reason, self.evidence_reference):
            require_text(value)
        require_hash(self.expected_source_hash)
        require_hash(self.evidence_hash)
        if self.decision == "cumulative_cancel":
            require_minor(self.target_minor)
        elif self.decision != "no_adjustment" or self.target_minor is not None:
            raise ValueError("financial_review_decision_invalid")
