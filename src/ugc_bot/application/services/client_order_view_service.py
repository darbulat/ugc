"""Current owner authorization precedes every order-list snapshot."""

from dataclasses import dataclass

from ugc_bot.application.client_order_view_ports import (
    ClientOrderViewRepository,
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
