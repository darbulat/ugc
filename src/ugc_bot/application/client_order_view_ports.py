"""Protected customer order summaries."""

from typing import Protocol
from uuid import UUID


class ClientOrderViewRepository(Protocol):
    async def page(
        self,
        owner_id: UUID,
        page: int,
        limit: int,
        status: str | None,
        *,
        session: object,
    ) -> dict: ...
