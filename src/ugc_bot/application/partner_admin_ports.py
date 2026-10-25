"""Explicit, versioned operational reviews; no financial journal authority."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID


def _provenance(command):
    for value in (command.actor_id,):
        if not isinstance(value, UUID) or not value.int:
            raise ValueError("admin_review_identity_required")
    for value, limit in ((command.operation_key, 256), (command.reason, 4000)):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
        ):
            raise ValueError("admin_review_reason_required")


@dataclass(frozen=True, slots=True)
class LeadReviewCommand:
    operation_key: str
    actor_id: UUID
    lead_id: UUID
    expected_version: int
    action: str
    manager_ids: tuple[UUID, ...]
    reason: str

    def __post_init__(self):
        _provenance(self)
        if not isinstance(self.lead_id, UUID) or not self.lead_id.int:
            raise ValueError("admin_review_identity_required")
        if type(self.expected_version) is not int or self.expected_version < 0:
            raise ValueError("lead_version_required")
        if self.action not in ("accept", "reject"):
            raise ValueError("lead_review_action_invalid")
        if (
            type(self.manager_ids) is not tuple
            or len(self.manager_ids) > 20
            or len(set(self.manager_ids)) != len(self.manager_ids)
            or any(
                not isinstance(uid, UUID) or not uid.int
                for uid in self.manager_ids
            )
            or (self.action == "accept" and not self.manager_ids)
            or (self.action == "reject" and self.manager_ids)
        ):
            raise ValueError("lead_review_managers_invalid")


@dataclass(frozen=True, slots=True)
class BindingCorrectionCommand:
    operation_key: str
    actor_id: UUID
    referred_id: UUID
    expected_referrer_id: UUID
    referrer_id: UUID
    reason: str

    def __post_init__(self):
        _provenance(self)
        if any(
            not isinstance(uid, UUID) or not uid.int
            for uid in (
                self.referred_id,
                self.expected_referrer_id,
                self.referrer_id,
            )
        ):
            raise ValueError("admin_review_identity_required")


def command_hash(command):
    return hashlib.sha256(
        json.dumps(
            asdict(command), sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


class PartnerAdminRepository(Protocol):
    async def lock_users(self, ids, *, session): ...
    async def command(self, key, *, session): ...
    async def lead_for_update(self, lead_id, *, session): ...
    async def save_lead_review(
        self, command, result, digest, at, *, session
    ): ...
    async def binding_for_update(self, referred_id, *, session): ...
    async def save_binding_correction(
        self, command, result, digest, at, *, session
    ): ...
    async def queue_leads(self, page, status, *, session): ...
