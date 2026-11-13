"""Self-service cancellation of unpaid Telegram orders."""

from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.financial import utc


class OrderCancellationService(CustomerWorkflowService):
    async def cancel(
        self,
        user_id: UUID,
        order_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal,
        confirm: bool,
    ) -> str:
        if principal.platform != "telegram":
            raise PermissionError("telegram_cancellation_required")
        async with self.transactions.transaction() as session:
            await self.authorize(user_id, principal, session=session)
            return await self.repository.cancel_unpaid_order(
                user_id,
                order_id,
                utc(self.clock.now()),
                confirm=confirm,
                session=session,
            )

    async def cancelled_orders(self, order_ids: list[UUID]) -> set[UUID]:
        if not order_ids:
            return set()
        async with self.transactions.transaction() as session:
            return await self.repository.customer_cancelled_orders(
                order_ids, session=session
            )
