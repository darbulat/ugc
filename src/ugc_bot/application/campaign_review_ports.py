"""Draft persistence and private audience facts; no delivery capabilities."""

from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import UUID


class CampaignReviewRepository(Protocol):
    async def draft(
        self, owner_id: UUID, campaign_id: UUID, *, session: object
    ) -> dict[str, Any] | None: ...
    async def command(
        self, actor_id: UUID, key: str, *, session: object
    ) -> dict[str, Any] | None: ...
    async def save(
        self,
        values: dict[str, Any],
        receipt: dict[str, Any],
        *,
        session: object,
    ) -> None: ...
    async def list_drafts(
        self, owner_id: UUID, page: int, *, session: object
    ) -> list[dict[str, Any]]: ...
    def candidates(
        self, owner_id: UUID, *, session: object
    ) -> AsyncIterator[dict[str, Any]]: ...
