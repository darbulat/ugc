"""Reviewed real accompaniment refunds; no automatic bank transfers."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ugc_bot.application.collaboration_ports import CollaborationRecord
from ugc_bot.application.entitlement_ports import ClientCapture
from ugc_bot.domain.corrections import (
    require_hash,
    require_minor,
    require_text,
    require_uuid,
    require_version,
)
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class AccompanimentRefundScope:
    capture: ClientCapture
    record: CollaborationRecord | None
    original_payment_reference: str
    manager_earned: bool = False
    paid_item_id: UUID | None = None

    def __post_init__(self):
        item_id = self.paid_item_id
        if self.record is not None:
            if item_id is not None and item_id != self.record.paid_item_id:
                raise ValueError("accompaniment_capture_scope_mismatch")
            item_id = self.record.paid_item_id
        require_uuid(item_id)
        if not any(i.paid_item_id == item_id for i in self.capture.items):
            raise ValueError("accompaniment_capture_scope_mismatch")
        if self.record is None and self.manager_earned:
            raise ValueError("accompaniment_manager_ground_review_required")
        object.__setattr__(self, "paid_item_id", item_id)

    @property
    def work_version(self):
        return self.record.version if self.record is not None else 0

    @property
    def work_stage(self):
        return self.record.collaboration.state.value if self.record else None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveAccompanimentRefund:
    actor_id: UUID
    operation_key: str
    paid_item_id: UUID
    original_payment_reference: str
    amount_minor: int
    currency: str
    bank_account_label: str
    bank_reference: str
    occurred_at: datetime
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        for value in (self.actor_id, self.paid_item_id):
            require_uuid(value)
        for value in (
            self.operation_key,
            self.original_payment_reference,
            self.bank_account_label,
            self.bank_reference,
            self.reason,
            self.evidence_reference,
        ):
            require_text(value)
        require_minor(self.amount_minor, positive=True)
        require_text(self.currency, 64)
        require_hash(self.evidence_hash)
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyAccompanimentRefund:
    actor_id: UUID
    operation_key: str
    observation_id: UUID
    paid_item_id: UUID
    expected_work_version: int
    reason: str
    evidence_reference: str
    evidence_hash: str
    reviewed_customer_target_minor: int | None = None
    reviewed_manager_target_minor: int | None = None

    def __post_init__(self):
        for value in (self.actor_id, self.observation_id, self.paid_item_id):
            require_uuid(value)
        require_minor(self.expected_work_version)
        for value in (self.operation_key, self.reason, self.evidence_reference):
            require_text(value)
        require_hash(self.evidence_hash)
        for value in (
            self.reviewed_customer_target_minor,
            self.reviewed_manager_target_minor,
        ):
            if value is not None:
                require_minor(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewAccompanimentManagement:
    actor_id: UUID
    operation_key: str
    application_id: UUID
    paid_item_id: UUID
    expected_work_version: int
    decision: str
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        for value in (self.actor_id, self.application_id, self.paid_item_id):
            require_uuid(value)
        require_version(self.expected_work_version)
        if self.decision not in ("continue", "cancel"):
            raise ValueError("accompaniment_management_decision_invalid")
        for value in (self.operation_key, self.reason, self.evidence_reference):
            require_text(value)
        require_hash(self.evidence_hash)
