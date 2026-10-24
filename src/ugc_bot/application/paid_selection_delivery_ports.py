"""One-shot paid contact delivery with durable source and lease fencing."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.notice_delivery_ports import DeliveryContact


@dataclass(frozen=True, slots=True)
class SelectionDeliveryJob:
    job_id: UUID
    interest_id: UUID
    order_id: UUID
    created_at: datetime
    state: str
    attempt_count: int
    current_attempt_id: UUID | None
    lease_token: UUID | None
    lease_until: datetime | None


@dataclass(frozen=True, slots=True)
class SelectionDeliverySource:
    job_id: UUID
    interest_id: UUID
    order_id: UUID
    client_id: UUID
    creator_id: UUID
    paid_item_id: UUID
    assignment_id: UUID
    assignment_version: int
    manager_id: UUID | None
    payment_id: UUID
    capture_event_id: UUID
    allocation_key: str
    policy_version: str
    currency: str
    instagram_user_id: str
    instagram_url: str
    confirmed_at: datetime
    due_at: datetime
    contact: DeliveryContact | None
    creator_contact: dict
    source_hash: str
    invalid_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionDeliveryAttempt:
    attempt_id: UUID
    job_id: UUID
    interest_id: UUID
    order_id: UUID
    source: dict
    source_hash: str
    number: int
    lease_token: UUID
    prepared_at: datetime
    lease_until: datetime
    channel: str | None
    address: str | None
    address_kind: str
    locale: str
    text: str
    action_url: str | None = None
    action_label: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionDeliveryOutcome:
    outcome_id: UUID
    job_id: UUID
    order_id: UUID
    attempt_id: UUID | None
    kind: str
    status: str
    recorded_at: datetime
    provider_reference: str | None
    reason: str | None
    applied: bool


class PaidSelectionDeliveryRepository(Protocol):
    async def candidates(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[UUID, ...]: ...
    async def lock_source(
        self, job_id: UUID, at: datetime, *, session: object
    ) -> SelectionDeliverySource | None: ...
    async def job(
        self, job_id: UUID, *, session: object
    ) -> SelectionDeliveryJob | None: ...
    async def save_job(
        self, job: SelectionDeliveryJob, *, session: object
    ) -> None: ...
    async def save_attempt(
        self, attempt: SelectionDeliveryAttempt, *, session: object
    ) -> None: ...
    async def attempt(
        self, attempt_id: UUID, *, session: object
    ) -> SelectionDeliveryAttempt: ...
    async def outcome(
        self, outcome_id: UUID, *, session: object
    ) -> SelectionDeliveryOutcome | None: ...
    async def save_outcome(
        self, outcome: SelectionDeliveryOutcome, *, session: object
    ) -> None: ...
    async def receipt_used(
        self, channel: str, reference: str, *, session: object
    ) -> bool: ...
    async def accept(
        self,
        attempt: SelectionDeliveryAttempt,
        source: SelectionDeliverySource,
        outcome: SelectionDeliveryOutcome,
        *,
        session: object,
    ) -> None: ...
