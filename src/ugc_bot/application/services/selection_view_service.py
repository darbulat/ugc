"""One read-only snapshot for order, assignments, queue and accepted facts."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.selection_view_ports import SelectionViewRepository


@dataclass
class SelectionViewService:
    repository: SelectionViewRepository
    transactions: TransactionManager

    async def view(
        self,
        order_id: UUID,
        actor_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        if principal is not None and (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        async with self.transactions.transaction() as session:
            await self.repository.begin_snapshot(session=session)
            return await self.repository.view(
                order_id, actor_id, session=session, principal=principal
            )
