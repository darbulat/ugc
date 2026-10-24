"""Creator-work state transitions, separate from paid selection and money.

Commands operate on server-assessed assignment identities. Persistence, current
roles, idempotency, notification I/O and ledger commands belong to application
services; this object neither authorizes a payout nor invents its release fact.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from ugc_bot.domain.financial import utc


class CollaborationState(StrEnum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    SUCCESS_CLAIMED = "success_claimed"
    DISPUTED = "disputed"
    SUCCESS_FINAL = "success_final"
    UNCONFIRMED_EXPIRED = "unconfirmed_expired"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True, kw_only=True)
class Collaboration:
    assignment_id: UUID
    client_id: UUID
    creator_id: UUID
    manager_id: UUID | None
    due_at: datetime
    agreed_at: datetime
    state: CollaborationState = CollaborationState.ASSIGNED
    due_version: int = 1
    claimant_id: UUID | None = None
    claimed_at: datetime | None = None
    evidence: str | None = None
    notice_delivered_at: datetime | None = None
    notice_failed_at: datetime | None = None
    dispute_reason: str | None = None
    disputed_at: datetime | None = None
    success_final_at: datetime | None = None

    def __post_init__(self) -> None:
        for value in (self.assignment_id, self.client_id, self.creator_id):
            if not isinstance(value, UUID) or value.int == 0:
                raise ValueError("collaboration_identity_required")
        if self.manager_id is not None and (
            not isinstance(self.manager_id, UUID) or self.manager_id.int == 0
        ):
            raise ValueError("collaboration_identity_required")
        object.__setattr__(self, "state", CollaborationState(self.state))
        for field in (
            "due_at",
            "agreed_at",
            "claimed_at",
            "notice_delivered_at",
            "notice_failed_at",
            "disputed_at",
            "success_final_at",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, utc(value))
        if self.due_at is None or self.agreed_at is None:
            raise ValueError("agreed_due_at_required")
        if self.due_at <= self.agreed_at:
            raise ValueError("agreed_due_at_required")
        if type(self.due_version) is not int or self.due_version < 1:
            raise ValueError("due_version_required")

    @property
    def first_claim_deadline(self) -> datetime:
        return self.due_at + timedelta(days=14)

    @property
    def objection_deadline(self) -> datetime | None:
        if self.claimed_at is None:
            return None
        return self.claimed_at + timedelta(hours=72)

    @property
    def available_at(self) -> datetime | None:
        if self.success_final_at is None:
            return None
        return self.success_final_at + timedelta(days=14)

    def _time(self, at: datetime) -> datetime:
        at = utc(at)
        if at < self.agreed_at or (
            self.claimed_at is not None and at < self.claimed_at
        ):
            raise ValueError("collaboration_time_conflict")
        return at

    def _require_state(self, *states: CollaborationState) -> None:
        if self.state not in states:
            raise ValueError("collaboration_state_conflict")

    def _opposite_party(self, actor_id: UUID) -> None:
        if (
            actor_id not in (self.client_id, self.creator_id)
            or actor_id == self.claimant_id
        ):
            raise ValueError("opposite_party_required")

    def start(self, *, actor_id: UUID, at: datetime) -> "Collaboration":
        self._time(at)
        self._require_state(CollaborationState.ASSIGNED)
        if not isinstance(actor_id, UUID) or actor_id not in (
            self.client_id,
            self.manager_id,
        ):
            raise ValueError("assignment_actor_required")
        return replace(self, state=CollaborationState.IN_PROGRESS)

    def claim_success(
        self, *, actor_id: UUID, evidence: str, at: datetime
    ) -> "Collaboration":
        at = self._time(at)
        self._require_state(CollaborationState.IN_PROGRESS)
        if actor_id not in (self.client_id, self.creator_id):
            raise ValueError("collaboration_party_required")
        if at >= self.first_claim_deadline:
            raise ValueError("claim_window_closed")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("evidence_required")
        return replace(
            self,
            state=CollaborationState.SUCCESS_CLAIMED,
            claimant_id=actor_id,
            claimed_at=at,
            evidence=evidence.strip(),
        )

    def record_notice(self, *, accepted: bool, at: datetime) -> "Collaboration":
        at = self._time(at)
        self._require_state(CollaborationState.SUCCESS_CLAIMED)
        if type(accepted) is not bool:
            raise ValueError("notice_result_required")
        if accepted:
            return replace(
                self, notice_delivered_at=self.notice_delivered_at or at
            )
        return replace(self, notice_failed_at=self.notice_failed_at or at)

    def _finalize(self, at: datetime) -> "Collaboration":
        return replace(
            self,
            state=CollaborationState.SUCCESS_FINAL,
            success_final_at=at,
        )

    def agree(self, *, actor_id: UUID, at: datetime) -> "Collaboration":
        at = self._time(at)
        self._require_state(CollaborationState.SUCCESS_CLAIMED)
        self._opposite_party(actor_id)
        return self._finalize(at)

    def dispute(
        self, *, actor_id: UUID, reason: str, at: datetime
    ) -> "Collaboration":
        at = self._time(at)
        self._require_state(CollaborationState.SUCCESS_CLAIMED)
        self._opposite_party(actor_id)
        deadline = self.objection_deadline
        assert deadline is not None
        if at >= deadline:
            raise ValueError("objection_window_closed")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("dispute_reason_required")
        return replace(
            self,
            state=CollaborationState.DISPUTED,
            dispute_reason=reason.strip(),
            disputed_at=at,
        )

    def advance(self, *, at: datetime) -> "Collaboration":
        at = self._time(at)
        if (
            self.state
            in (
                CollaborationState.ASSIGNED,
                CollaborationState.IN_PROGRESS,
            )
            and at >= self.first_claim_deadline
        ):
            return replace(self, state=CollaborationState.UNCONFIRMED_EXPIRED)
        deadline = self.objection_deadline
        if (
            self.state == CollaborationState.SUCCESS_CLAIMED
            and deadline is not None
            and at >= deadline
            and self.notice_delivered_at is not None
            and self.notice_delivered_at < deadline
            and self.notice_failed_at is None
        ):
            return self._finalize(deadline)
        available_at = self.available_at
        if (
            self.state == CollaborationState.SUCCESS_FINAL
            and available_at is not None
            and at >= available_at
        ):
            return replace(self, state=CollaborationState.AVAILABLE)
        return self

    def extend_due(
        self,
        *,
        actor_id: UUID,
        due_at: datetime,
        expected_due_version: int,
        at: datetime,
    ) -> "Collaboration":
        at = self._time(at)
        due_at = utc(due_at)
        self._require_state(
            CollaborationState.ASSIGNED,
            CollaborationState.IN_PROGRESS,
            CollaborationState.SUCCESS_CLAIMED,
        )
        if actor_id != self.client_id:
            raise ValueError("client_consent_required")
        if (
            type(expected_due_version) is not int
            or expected_due_version != self.due_version
        ):
            raise ValueError("due_version_conflict")
        if due_at <= self.due_at or due_at <= at:
            raise ValueError("agreed_due_at_required")
        if self.claimed_at is None and at >= self.first_claim_deadline:
            raise ValueError("claim_window_closed")
        return replace(self, due_at=due_at, due_version=self.due_version + 1)
