"""Caller-transaction creator-work contracts; no financial entitlement DTOs."""

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from dataclasses import field as dataclass_field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.collaboration import Collaboration, CollaborationState
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class CollaborationActor:
    user_id: UUID
    status: str
    is_client: bool = False
    is_creator: bool = False
    is_admin: bool = False
    manager_order_ids: tuple[UUID, ...] = ()
    telegram_id: str | None = None
    max_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CollaborationScope:
    """Server-loaded assignment, ownership and captured selection facts."""

    assignment_id: UUID
    paid_item_id: UUID
    order_id: UUID
    client_id: UUID
    creator_id: UUID
    manager_id: UUID | None
    policy_version: str | None
    captured_at: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    selection_funded: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CollaborationPrincipalScope:
    """One preparation, bound to its caller's active root transaction."""

    assignment_id: UUID
    paid_item_id: UUID
    order_id: UUID
    client_id: UUID
    creator_id: UUID
    manager_id: UUID | None
    actor_id: UUID
    user_ids: tuple[UUID, ...]
    owner_session: object = dataclass_field(repr=False, compare=False)
    root_transaction: object = dataclass_field(repr=False, compare=False)

    @property
    def source_identity(self) -> tuple:
        return (
            self.assignment_id,
            self.paid_item_id,
            self.order_id,
            self.client_id,
            self.creator_id,
            self.manager_id,
        )

    def require_source(self, scope: CollaborationScope) -> None:
        if self.source_identity != (
            scope.assignment_id,
            scope.paid_item_id,
            scope.order_id,
            scope.client_id,
            scope.creator_id,
            scope.manager_id,
        ):
            raise ValueError("collaboration_scope_changed")


@dataclass(frozen=True, slots=True, kw_only=True)
class CollaborationCommand:
    """Internal command; ingress must supply verified actor, never body roles.

    System producer fields belong to trusted scheduler/transport adapters.
    Never deserialize them from frontend requests. The service supplies time.
    """

    assignment_id: UUID
    action: str
    operation_key: str
    expected_version: int
    actor_id: UUID | None = None
    system_actor: str | None = None
    due_at: datetime | None = None
    expected_due_version: int | None = None
    terms_reference: str | None = None
    evidence: str | None = None
    reason: str | None = None
    notice_id: UUID | None = None
    accepted: bool | None = None
    channel: str | None = None
    external_reference: str | None = None


@dataclass(frozen=True, slots=True)
class CollaborationRecord:
    collaboration: Collaboration
    paid_item_id: UUID
    order_id: UUID
    policy_version: str
    terms_reference: str
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CollaborationEvent:
    event_id: UUID
    assignment_id: UUID
    operation_key: str
    payload_hash: str
    event_type: str
    actor_id: UUID | None
    system_actor: str | None
    parameters: dict
    result: CollaborationRecord
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class CollaborationNotice:
    notice_id: UUID
    assignment_id: UUID
    source_event_id: UUID
    purpose: str
    recipient_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CollaborationReleaseSchedule:
    """Immutable work maturity fact, not funding or a payout authorization."""

    schedule_id: UUID
    assignment_id: UUID
    source_event_id: UUID
    success_final_at: datetime
    release_at: datetime


def canonical(value):
    if isinstance(value, (UUID, datetime)):
        return (
            utc(value).isoformat()
            if isinstance(value, datetime)
            else str(value)
        )
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def command_hash(command: CollaborationCommand) -> str:
    encoded = json.dumps(
        canonical(asdict(command)), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def record_payload(record: CollaborationRecord) -> dict:
    return canonical(asdict(record))


def record_from_payload(payload: dict) -> CollaborationRecord:
    data = dict(payload["collaboration"])
    for field in fields(Collaboration):
        value = data.get(field.name)
        if value is not None and field.name.endswith("_id"):
            data[field.name] = UUID(value)
        elif value is not None and field.name.endswith("_at"):
            data[field.name] = datetime.fromisoformat(value)
    return CollaborationRecord(
        Collaboration(**data),
        UUID(payload["paid_item_id"]),
        UUID(payload["order_id"]),
        payload["policy_version"],
        payload["terms_reference"],
        payload["version"],
        datetime.fromisoformat(payload["updated_at"]),
    )


def next_transition_at(work: Collaboration) -> datetime | None:
    if work.state in (
        CollaborationState.ASSIGNED,
        CollaborationState.IN_PROGRESS,
    ):
        return work.first_claim_deadline
    if work.state == CollaborationState.SUCCESS_FINAL:
        return work.available_at
    deadline = work.objection_deadline
    if (
        work.state == CollaborationState.SUCCESS_CLAIMED
        and deadline is not None
        and work.notice_delivered_at is not None
        and work.notice_failed_at is None
        and work.notice_delivered_at < deadline
    ):
        return deadline
    return None


class CollaborationRepository(Protocol):
    async def lock_admin_actor(
        self, actor_id: UUID, *, session: object
    ) -> CollaborationActor | None: ...
    async def list_disputes(
        self, limit: int, cursor: UUID | None, *, session: object
    ) -> tuple[CollaborationRecord, ...]: ...

    async def prepare_principal_scope(
        self,
        assignment_id: UUID,
        actor_id: UUID,
        principal: AuthenticatedMessengerPrincipal,
        *,
        session: object,
    ) -> CollaborationPrincipalScope | None: ...

    async def lock_scope(
        self,
        assignment_id: UUID,
        *,
        session: object,
        expected_scope: CollaborationPrincipalScope | None = None,
    ) -> CollaborationScope: ...

    async def load_actor(
        self, actor_id: UUID, *, session: object
    ) -> CollaborationActor | None: ...

    async def get(
        self, assignment_id: UUID, *, session: object
    ) -> CollaborationRecord | None: ...

    async def get_command(
        self, assignment_id: UUID, operation_key: str, *, session: object
    ) -> CollaborationEvent | None: ...

    async def get_event_for_version(
        self, assignment_id: UUID, version: int, *, session: object
    ) -> CollaborationEvent | None: ...

    async def get_notice(
        self, notice_id: UUID, *, session: object
    ) -> CollaborationNotice | None: ...

    async def persist(
        self,
        event: CollaborationEvent,
        *,
        notices: tuple[CollaborationNotice, ...],
        schedule: CollaborationReleaseSchedule | None,
        session: object,
    ) -> None: ...

    async def list_due(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[CollaborationRecord, ...]: ...
