"""Explicit reserve replacement commands; paid capture remains authoritative."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


def _identity(value):
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("replacement_identity_required")


def _text(value, *, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError("replacement_reason_evidence_required")


def _command(command):
    _identity(command.actor_id)
    if (
        not isinstance(command.operation_key, str)
        or not command.operation_key.strip()
        or len(command.operation_key) > 256
    ):
        raise ValueError("replacement_operation_key_required")
    _text(command.reason)
    _text(command.evidence_reference)


@dataclass(frozen=True, slots=True)
class ReplacementRequest:
    operation_key: str
    actor_id: UUID
    paid_item_id: UUID
    expected_assignment_version: int
    candidate_interest_id: UUID
    reason_code: str
    reason: str
    evidence_reference: str

    def __post_init__(self):
        _command(self)
        for value in (self.paid_item_id, self.candidate_interest_id):
            _identity(value)
        if (
            type(self.expected_assignment_version) is not int
            or self.expected_assignment_version < 1
        ):
            raise ValueError("replacement_assignment_version_required")
        if self.reason_code not in (
            "refusal",
            "lost_contact",
            "brief_mismatch",
        ):
            raise ValueError("replacement_reason_code_invalid")


@dataclass(frozen=True, slots=True)
class ReplacementDecision:
    operation_key: str
    actor_id: UUID
    request_id: UUID
    expected_version: int
    action: str
    reason: str
    evidence_reference: str
    manager_id: UUID | None = None
    exception_reason: str | None = None
    exception_evidence: str | None = None

    def __post_init__(self):
        _command(self)
        _identity(self.request_id)
        if self.manager_id is not None:
            _identity(self.manager_id)
        if type(self.expected_version) is not int or self.expected_version != 1:
            raise ValueError("replacement_request_version_required")
        if self.action not in ("approve", "reject"):
            raise ValueError("replacement_action_invalid")
        if (self.exception_reason is None) != (self.exception_evidence is None):
            raise ValueError("replacement_reason_evidence_required")
        _text(self.exception_reason, optional=True)
        _text(self.exception_evidence, optional=True)


@dataclass(frozen=True, slots=True)
class ReplacementContact:
    operation_key: str
    actor_id: UUID
    replacement_id: UUID
    reason: str
    evidence_reference: str

    def __post_init__(self):
        _command(self)
        _identity(self.replacement_id)


@dataclass(frozen=True, slots=True)
class ReplacementCandidate:
    interest_id: UUID
    order_id: UUID
    creator_id: UUID
    payment_id: UUID
    capture_event_id: UUID
    policy_version: str
    confirmed_at: datetime
    instagram_user_id: str
    instagram_url: str
    verified: bool
    used: bool


@dataclass(frozen=True, slots=True)
class ReplacementScope:
    paid_item_id: UUID
    order_id: UUID
    client_id: UUID
    payment_id: UUID
    capture_event_id: UUID
    policy_version: str
    captured_at: datetime
    capture_hash: str
    original_paid_pool: int
    selection_state: str
    order_active: bool
    assignment_id: UUID
    assignment_version: int
    creator_id: UUID
    manager_id: UUID | None
    assignment_from: datetime
    assignment_ids: tuple[UUID, ...]
    creator_ids: tuple[UUID, ...]
    manager_ids: tuple[UUID, ...]
    accompaniment: bool
    replacement_count: int
    completed_work: bool


def replacement_hash(command) -> str:
    return hashlib.sha256(
        json.dumps(
            asdict(command), default=str, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class ReplacementRepository(Protocol):
    async def load_scope(
        self, item_id: UUID, *, session: object
    ) -> ReplacementScope: ...
    async def lock_scope(
        self, scope: ReplacementScope, *, session: object
    ) -> None: ...
    async def load_actor(self, actor_id: UUID, *, session: object): ...
    async def candidate(
        self, interest_id: UUID, *, session: object
    ) -> ReplacementCandidate | None: ...
    async def get_command(
        self, actor_id: UUID, key: str, *, session: object
    ): ...
    async def save_command(
        self,
        actor_id: UUID,
        key: str,
        digest: str,
        result: dict,
        *,
        session: object,
    ) -> None: ...
    async def append_request(self, fact: dict, *, session: object) -> None: ...
    async def request(
        self, request_id: UUID, *, session: object
    ) -> dict | None: ...
    async def decision(
        self, request_id: UUID, *, session: object
    ) -> dict | None: ...
    async def append_decision(self, fact: dict, *, session: object) -> None: ...
    async def replace_assignment(
        self,
        scope,
        candidate,
        manager_id,
        actor_id,
        reason,
        at,
        *,
        session: object,
    ) -> UUID: ...
    async def append_allocation(
        self, fact: dict, *, session: object
    ) -> None: ...
    async def require_clear(
        self, item_id: UUID, *, session: object
    ) -> None: ...
