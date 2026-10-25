"""Append-only commercial evidence, distinct from financial income ledger."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SubscriptionCampaignUse:
    member_id: UUID
    campaign_id: UUID
    outcome_id: UUID


class SubscriptionRepository(Protocol):
    async def context(
        self, actor_id: UUID, member_id: UUID, *, session: object
    ) -> dict: ...

    async def lock(self, *, session: object) -> None: ...

    async def events(self, *, session: object) -> list[dict]: ...

    async def pilot_reuse(
        self, first_paid: dict[UUID, datetime], *, session: object
    ) -> tuple[SubscriptionCampaignUse, ...]: ...

    async def append(self, event: dict, *, session: object) -> None: ...
