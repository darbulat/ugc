"""Durable admin lead notices are operational facts, never money authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.notice_delivery_ports import (
    DeliveryContact,
    DeliveryReceipt,
)
from ugc_bot.domain.order_intake import AccompanimentLead


@dataclass(frozen=True, slots=True)
class LeadDeliveryJob:
    job_id: UUID
    lead_id: UUID
    order_id: UUID
    recipient_id: UUID
    state: str = "ready"
    attempt_count: int = 0
    current_attempt_id: UUID | None = None
    lease_token: UUID | None = None
    lease_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeadAttempt:
    attempt_id: UUID
    job_id: UUID
    lead_id: UUID
    order_id: UUID
    recipient_id: UUID
    number: int
    lease_token: UUID
    prepared_at: datetime
    lease_until: datetime
    channel: str | None
    address: str | None
    address_kind: str
    text: str
    action_url: str | None = None
    action_label: str | None = None


@dataclass(frozen=True, slots=True)
class LeadOutcome:
    outcome_id: UUID
    attempt_id: UUID
    job_id: UUID
    lead_id: UUID
    order_id: UUID
    kind: str
    status: str
    recorded_at: datetime
    provider_reference: str | None = None
    reason: str | None = None
    applied: bool = True
    actor_id: UUID | None = None
    operation_key: str | None = None
    payload_hash: str | None = None


class LeadReceiptTransport(Protocol):
    async def send(self, attempt: LeadAttempt) -> DeliveryReceipt: ...


class AccompanimentLeadDeliveryRepository(Protocol):
    async def expand(
        self, at: datetime, limit: int, *, session: object
    ) -> None: ...
    async def candidates(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[UUID, ...]: ...
    async def lock_job(
        self, job_id: UUID, *, session: object
    ) -> LeadDeliveryJob | None: ...
    async def lead(
        self, lead_id: UUID, *, session: object
    ) -> AccompanimentLead: ...
    async def contact(
        self, user_id: UUID, *, session: object
    ) -> DeliveryContact | None: ...
    async def is_admin(self, user_id: UUID, *, session: object) -> bool: ...
    async def save_job(
        self, job: LeadDeliveryJob, *, session: object
    ) -> None: ...
    async def save_attempt(
        self, attempt: LeadAttempt, *, session: object
    ) -> None: ...
    async def get_attempt(
        self, attempt_id: UUID, *, session: object
    ) -> LeadAttempt: ...
    async def save_outcome(
        self, outcome: LeadOutcome, *, session: object
    ) -> None: ...
    async def command_outcome(
        self, operation_key: str, *, session: object
    ) -> LeadOutcome | None: ...
