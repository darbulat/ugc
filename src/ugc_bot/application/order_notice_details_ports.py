"""Read-only persisted quote projection for customer and admin messages."""

from typing import Protocol
from uuid import UUID


class OrderNoticeDetailsRepository(Protocol):
    async def load(self, order_id: UUID, *, session: object) -> dict | None: ...
