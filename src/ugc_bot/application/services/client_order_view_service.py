"""Current owner authorization precedes every order-list snapshot."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.client_order_view_ports import (
    ClientOrderViewRepository,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.enums import OrderStatus


@dataclass
class ClientOrderViewService(CustomerWorkflowService):
    views: ClientOrderViewRepository

    async def list(
        self, actor_id, *, page=0, limit=10, status=None, principal=None
    ):
        if (
            type(page) is not int
            or page < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("order_page_invalid")
        if status is not None and status not in {
            state.value for state in OrderStatus
        }:
            raise ValueError("order_status_invalid")
        async with self.transactions.transaction() as session:
            await self.authorize(actor_id, principal, session=session)
            return await self.views.page(
                actor_id, page, limit, status, session=session
            )

    async def payment_states(
        self,
        principal: AuthenticatedMessengerPrincipal,
        order_ids: Sequence[UUID],
    ) -> dict[UUID, str]:
        """Read existing payment facts for the customer's visible orders."""
        async with self.transactions.transaction() as session:
            await self.authorize(principal.user_id, principal, session=session)
            states = {}
            for order_id in order_ids:
                await self.require_order(
                    principal.user_id, order_id, session=session
                )
                states[order_id] = await self.repository.payment_state(
                    order_id, session=session
                )
            return states
