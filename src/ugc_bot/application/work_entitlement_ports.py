"""Server-loaded work/funding facts and the transactional assessment inbox."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.collaboration_ports import (
    CollaborationRecord,
    CollaborationScope,
)
from ugc_bot.application.entitlement_ports import ClientCapture
from ugc_bot.domain.entities import OutboxEvent

WORK_EVENT_TYPES = frozenset(
    "financial.collaboration." + suffix
    for suffix in (
        "assigned",
        "started",
        "success_claimed",
        "disputed",
        "success_final",
        "hold_matured",
        "expired",
        "checked",
        "notice_accepted",
        "notice_failed",
        "due_extended",
        "confirmation_requested",
        "rejected",
        "management_reviewed",
    )
)


@dataclass(frozen=True, slots=True)
class WorkEntitlementSnapshot:
    scope: CollaborationScope
    record: CollaborationRecord
    capture: ClientCapture
    source_hash: str
    manager_linked: bool
    schedule_id: UUID | None = None
    current_event_id: UUID | None = None
    resolution_case_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkDisputeCase:
    case_id: UUID
    assignment_id: UUID
    paid_item_id: UUID
    source_event_id: UUID
    actor_id: UUID
    reason: str
    occurred_at: datetime


class WorkEntitlementRepository(Protocol):
    async def source_hash(
        self, event: OutboxEvent, *, session: object
    ) -> str: ...
    async def load(
        self, event: OutboxEvent, *, session: object
    ) -> WorkEntitlementSnapshot: ...
    async def lock_funding(
        self, snapshot: WorkEntitlementSnapshot, *, session: object
    ) -> None: ...
    async def get_receipt(
        self, event_id: UUID, *, session: object
    ) -> dict | None: ...
    async def save_receipt(
        self,
        event: OutboxEvent,
        snapshot: WorkEntitlementSnapshot,
        assessment: dict,
        *,
        recorded_at: datetime,
        session: object,
    ) -> None: ...
    async def get_dispute_case(
        self, paid_item_id: UUID, *, session: object
    ) -> WorkDisputeCase | None: ...
