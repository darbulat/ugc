"""Caller-owned campaign transactions; reads never mutate configuration."""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class CampaignRepository(Protocol):
    async def begin_snapshot(self, *, session: object) -> datetime: ...
    async def context(
        self,
        actor_id: UUID,
        target_id: UUID | None = None,
        *,
        lock: bool,
        session: object,
    ) -> dict[str, Any]: ...
    async def current(
        self, stream: str, subject: UUID | None = None, *, session: object
    ) -> dict[str, Any] | None: ...
    async def receipt(
        self, actor_id: UUID, key: str, *, session: object
    ) -> dict[str, Any] | None: ...
    async def known_terms(
        self, version: str, *, session: object
    ) -> str | None: ...
    async def append(
        self, stream: str, values: dict[str, Any], *, session: object
    ) -> None: ...
    async def save_receipt(
        self, values: dict[str, Any], *, session: object
    ) -> None: ...
    async def accounts(
        self, search: str, page: int, *, session: object
    ) -> list[dict[str, Any]]: ...
