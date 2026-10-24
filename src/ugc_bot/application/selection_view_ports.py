"""Own-client selection reads expose accepted facts without provider secrets."""

from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


class SelectionViewRepository(Protocol):
    async def begin_snapshot(self, *, session: object) -> None: ...

    async def view(
        self,
        order_id: UUID,
        client_id: UUID,
        *,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict: ...
