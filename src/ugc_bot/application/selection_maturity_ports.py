"""Actual selection resolution facts and immutable client release schedules."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from ugc_bot.application.collaboration_ports import CollaborationActor
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class SelectionPosition:
    paid_item_id: UUID
    delivered_at: datetime | None = None
    delivery_id: UUID | None = None
    refunded_at: datetime | None = None
    refund_application_id: UUID | None = None

    def __post_init__(self):
        if (
            not isinstance(self.paid_item_id, UUID)
            or self.paid_item_id.int == 0
        ):
            raise ValueError("selection_item_required")
        for timestamp, identity in (
            ("delivered_at", "delivery_id"),
            ("refunded_at", "refund_application_id"),
        ):
            at, source = getattr(self, timestamp), getattr(self, identity)
            if (at is None) != (source is None):
                raise ValueError("selection_resolution_provenance_required")
            if at is not None:
                if not isinstance(source, UUID) or source.int == 0:
                    raise ValueError("selection_resolution_provenance_required")
                object.__setattr__(self, timestamp, utc(at))

    @property
    def resolved_at(self):
        return self.delivered_at or self.refunded_at


@dataclass(frozen=True, slots=True)
class SelectionSnapshot:
    order_id: UUID
    client_id: UUID
    payment_id: UUID
    policy: FinancialPolicy
    captured_at: datetime
    positions: tuple[SelectionPosition, ...]

    def __post_init__(self):
        object.__setattr__(self, "captured_at", utc(self.captured_at))
        if not self.positions or len(
            {p.paid_item_id for p in self.positions}
        ) != len(self.positions):
            raise ValueError("selection_positions_required")
        if any(
            at is not None and at < self.captured_at
            for p in self.positions
            for at in (p.delivered_at, p.refunded_at)
        ):
            raise ValueError("selection_resolution_before_capture")


@dataclass(frozen=True, slots=True)
class SelectionClosure:
    closure_id: UUID
    order_id: UUID
    client_id: UUID
    payment_id: UUID
    policy_version: str
    closed_at: datetime
    source_document: dict
    actor_id: UUID | None
    reason: str
    evidence: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class SelectionMaturitySource:
    source_id: UUID
    closure_id: UUID
    paid_item_id: UUID
    order_id: UUID
    payment_id: UUID
    client_id: UUID
    policy_version: str
    refund_deadline_at: datetime
    hold_started_at: datetime
    release_at: datetime

    def __post_init__(self):
        for field in ("refund_deadline_at", "hold_started_at", "release_at"):
            object.__setattr__(self, field, utc(getattr(self, field)))
        if (
            self.release_at != self.hold_started_at + timedelta(days=14)
            or self.hold_started_at < self.refund_deadline_at
        ):
            raise ValueError("invalid_selection_maturity")

    def require_for(self, basis: IssueBasis):
        if (
            basis.kind != "client_referral"
            or basis.paid_item_id != self.paid_item_id
            or basis.order_id != self.order_id
            or basis.payment_id != self.payment_id
            or basis.referred_user_id != self.client_id
            or basis.policy_version != self.policy_version
        ):
            raise ValueError("selection_maturity_scope_mismatch")


class SelectionMaturityRepository(Protocol):
    async def load_actor(
        self, actor_id: UUID, *, session: object
    ) -> CollaborationActor | None: ...
    async def list_orders(
        self, *, after: UUID | None = None, limit: int = 100, session: object
    ) -> tuple[UUID, ...]: ...
    async def load(
        self, order_id: UUID, *, session: object
    ) -> SelectionSnapshot: ...
    async def lock_order(self, order_id: UUID, *, session: object) -> None: ...
    async def get_closure(
        self, order_id: UUID, *, session: object
    ) -> SelectionClosure | None: ...
    async def save_closure(
        self, closure: SelectionClosure, *, session: object
    ) -> SelectionClosure: ...
    async def save_schedule(
        self, schedule: SelectionMaturitySource, *, session: object
    ) -> SelectionMaturitySource: ...
    async def require_clear(
        self, item_id: UUID, *, session: object
    ) -> None: ...
