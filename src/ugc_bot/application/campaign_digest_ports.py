"""Durable informational summaries; no collaboration or money authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.notice_delivery_ports import DeliveryContact


@dataclass(frozen=True, slots=True)
class DigestSource:
    order_id: UUID
    recipient_id: UUID
    summary: dict
    contact: DeliveryContact
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DigestAttempt:
    attempt_id: UUID
    request_id: UUID
    lease_token: UUID
    prepared_at: datetime
    lease_until: datetime
    source: dict
    source_hash: str
    channel: str
    address: str
    address_kind: str
    locale: str
    text: str
    action_url: str
    action_label: str


class CampaignDigestRepository(Protocol):
    async def receipt_used(self, channel, reference, *, session) -> bool: ...

    async def due_scopes(self, at, limit, *, session) -> tuple: ...
    async def lock_source(
        self, order_id, recipient_id, at, *, session
    ) -> DigestSource | None: ...
    async def enqueue(self, source, at, *, session) -> UUID | None: ...
    async def candidates(self, at, limit, *, session) -> tuple[UUID, ...]: ...
    async def scope(self, request_id, *, session) -> tuple[UUID, UUID]: ...
    async def job(self, request_id, *, session) -> dict: ...
    async def save_job(
        self, request_id, state, *, session, **values
    ) -> None: ...
    async def save_attempt(self, attempt, *, session) -> None: ...
    async def attempt(self, request_id, *, session) -> DigestAttempt | None: ...
    async def outcome(self, attempt_id, kind, *, session) -> dict | None: ...
    async def save_outcome(
        self,
        request_id,
        attempt_id,
        kind,
        status,
        at,
        *,
        session,
        reference=None,
        reason=None,
        applied=False,
    ) -> None: ...
