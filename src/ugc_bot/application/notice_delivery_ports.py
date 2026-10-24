"""Durable attempts and provider acceptance; never read receipts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.collaboration_ports import (
    CollaborationEvent,
    CollaborationNotice,
)
from ugc_bot.domain.entities import OutboxEvent

NOTICE_EVENT_TYPE = "financial.collaboration.notice_requested"


@dataclass(frozen=True, slots=True)
class DeliveryContact:
    user_id: UUID
    channel: str
    address: str | None
    locale: str
    status: str
    address_kind: str = "chat_id"


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    channel: str
    reference: str


class DeliveryFailure(Exception):
    """Safe error code, with uncertainty when the provider may have accepted."""

    def __init__(self, code: str, *, uncertain: bool):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NoticeOrigin:
    event: OutboxEvent
    notice: CollaborationNotice | None
    source: CollaborationEvent | None


@dataclass(frozen=True, slots=True)
class DeliveryJob:
    event_id: UUID
    notice_id: UUID
    state: str = "ready"
    attempt_count: int = 0
    current_attempt_id: UUID | None = None
    lease_token: UUID | None = None
    lease_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class NoticeAttempt:
    attempt_id: UUID
    event_id: UUID
    notice_id: UUID
    assignment_id: UUID
    source_event_id: UUID
    recipient_id: UUID
    number: int
    lease_token: UUID
    prepared_at: datetime
    lease_until: datetime
    collaboration_version: int
    channel: str | None
    address: str | None
    address_kind: str
    locale: str
    text: str
    deadline: datetime
    action_url: str | None = None
    action_label: str | None = None


@dataclass(frozen=True, slots=True)
class NoticeOutcome:
    outcome_id: UUID
    attempt_id: UUID
    kind: str
    status: str
    recorded_at: datetime
    provider_reference: str | None
    reason: str | None
    applied: bool
    actor_id: UUID | None = None
    operation_key: str | None = None


class ReceiptMessage(Protocol):
    """Read-only provider payload without financial identifiers."""

    @property
    def channel(self) -> str | None: ...

    @property
    def address(self) -> str | None: ...

    @property
    def address_kind(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def action_url(self) -> str | None: ...

    @property
    def action_label(self) -> str | None: ...


class NoticeReceiptTransport(Protocol):
    async def send(self, message: ReceiptMessage) -> DeliveryReceipt: ...


class NoticeDeliveryRepository(Protocol):
    async def candidates(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[UUID, ...]: ...

    async def origin(
        self, event_id: UUID, *, session: object
    ) -> NoticeOrigin | None: ...

    async def contact(
        self, recipient_id: UUID, *, session: object
    ) -> DeliveryContact | None: ...

    async def lock_job(
        self, origin: NoticeOrigin, *, session: object
    ) -> DeliveryJob: ...

    async def save_job(self, job: DeliveryJob, *, session: object) -> None: ...

    async def save_attempt(
        self, attempt: NoticeAttempt, *, session: object
    ) -> None: ...

    async def get_attempt(
        self, attempt_id: UUID, *, session: object
    ) -> NoticeAttempt: ...

    async def list_outcomes(
        self, attempt_id: UUID, *, session: object
    ) -> tuple[NoticeOutcome, ...]: ...

    async def retry_outcome(
        self, operation_key: str, *, session: object
    ) -> NoticeOutcome | None: ...

    async def save_outcome(
        self, outcome: NoticeOutcome, *, session: object
    ) -> None: ...

    async def settle_event(
        self,
        event_id: UUID,
        state: str,
        at: datetime,
        reason: str | None = None,
        *,
        session: object,
    ) -> None: ...
