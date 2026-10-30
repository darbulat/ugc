"""Private, owner-scoped order attachments."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


@dataclass(frozen=True, slots=True)
class OrderImage:
    token: UUID
    owner_id: UUID
    byte_count: int
    sha256: str
    created_at: datetime
    expires_at: datetime
    order_id: UUID | None = None

    @property
    def reference(self) -> str:
        return f"order-image:{self.token}"


class OrderImageRepository(Protocol):
    async def authorize(
        self,
        owner: UUID,
        principal: AuthenticatedMessengerPrincipal | None,
        *,
        session: object,
    ) -> bool: ...
    async def save(self, value: OrderImage, *, session: object) -> None: ...
    async def get(
        self, token: UUID, *, session: object
    ) -> OrderImage | None: ...
    async def bind(
        self, token: UUID, order_id: UUID, *, session: object
    ) -> None: ...
    async def expired(
        self, at: datetime, *, session: object
    ) -> list[OrderImage]: ...
    async def delete(self, token: UUID, *, session: object) -> None: ...


class OrderImageStorage(Protocol):
    async def put(self, token: UUID, data: bytes) -> None: ...
    async def get(self, token: UUID) -> bytes: ...
    async def delete(self, token: UUID) -> None: ...
