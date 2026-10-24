"""Read facts for an order summary; no delivery or payment authority."""

from typing import Protocol
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


class CampaignSummaryRepository(Protocol):
    async def begin_snapshot(self, *, session: object) -> None: ...

    async def view(
        self,
        order_id: UUID,
        actor_id: UUID,
        *,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict: ...
