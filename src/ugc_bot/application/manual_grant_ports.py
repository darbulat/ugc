"""Explicit positive adjustments have their own authority and hold."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ugc_bot.domain.corrections import (
    require_currency,
    require_hash,
    require_minor,
    require_text,
    require_uuid,
)
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True, kw_only=True)
class ApproveManualGrant:
    actor_id: UUID
    operation_key: str
    paid_item_id: UUID
    recipient_id: UUID
    amount_minor: int
    currency: str
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        for value in (self.actor_id, self.paid_item_id, self.recipient_id):
            require_uuid(value)
        for value in (self.operation_key, self.reason, self.evidence_reference):
            require_text(value)
        require_minor(self.amount_minor, positive=True)
        require_currency(self.currency)
        require_hash(self.evidence_hash)


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualGrantSource:
    grant_id: UUID
    actor_id: UUID
    recipient_id: UUID
    paid_item_id: UUID
    order_id: UUID
    client_id: UUID
    payment_id: UUID
    capture_id: UUID
    policy_version: str
    amount_minor: int
    currency: str
    approved_at: datetime
    release_at: datetime
    reason: str

    def __post_init__(self):
        for value in (
            self.grant_id,
            self.actor_id,
            self.recipient_id,
            self.paid_item_id,
            self.order_id,
            self.client_id,
            self.payment_id,
            self.capture_id,
        ):
            require_uuid(value)
        require_minor(self.amount_minor, positive=True)
        require_currency(self.currency)
        require_text(self.policy_version)
        require_text(self.reason)
        object.__setattr__(self, "approved_at", utc(self.approved_at))
        object.__setattr__(self, "release_at", utc(self.release_at))
        if self.release_at != self.approved_at + timedelta(days=14):
            raise ValueError("manual_grant_hold_required")

    def require_for(self, basis):
        expected = (
            "manual-grant:" + str(self.grant_id),
            "manual_adjustment",
            self.actor_id,
            "admin",
            self.recipient_id,
            self.paid_item_id,
            self.order_id,
            self.client_id,
            self.payment_id,
            self.policy_version,
            self.amount_minor,
            self.currency,
            self.approved_at,
            self.release_at,
            str(self.grant_id),
            self.reason,
        )
        actual = (
            basis.business_key,
            basis.kind,
            basis.actor_id,
            basis.actor_kind,
            basis.recipient_id,
            basis.paid_item_id,
            basis.order_id,
            basis.referred_user_id,
            basis.payment_id,
            basis.policy_version,
            basis.base_minor,
            basis.currency,
            basis.snapshot_at,
            basis.available_at,
            basis.event_id,
            basis.reason,
        )
        if actual != expected:
            raise ValueError("manual_grant_source_mismatch")


@dataclass(frozen=True, slots=True)
class ManualGrantAuthority:
    superadmin_user_ids: tuple[str, ...]
