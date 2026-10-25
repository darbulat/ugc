"""Nonfinancial campaign delivery and optional paid-access contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID


class CampaignAccess(Protocol):
    async def require_access(
        self,
        owner_id: UUID,
        *,
        action: Literal["submit", "send"],
        at: datetime,
        session: object,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CampaignAttempt:
    attempt_id: UUID
    job_id: UUID
    channel: str
    address: str
    address_kind: str
    text: str
    action_url: str
    action_label: str
    started_at: datetime
    deadline: datetime


class CampaignDeliveryRepository(Protocol):
    async def pending(
        self, at: datetime, limit: int, *, session: object
    ) -> tuple[UUID, ...]: ...
    async def prepare(
        self,
        job_id: UUID,
        at: datetime,
        *,
        access: CampaignAccess | None,
        session: object,
    ) -> CampaignAttempt | None: ...
    async def finish(
        self,
        attempt: CampaignAttempt,
        status: str,
        reference: str | None,
        reason: str | None,
        at: datetime,
        *,
        session: object,
    ) -> None: ...
