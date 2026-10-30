"""Typed service inquiries never create an order or financial entitlement."""

from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.customer_workflows import (
    CATALOG,
    RESULT_REQUIRED,
    ServiceLeadInput,
)


class ServiceLeadService(CustomerWorkflowService):
    async def create(
        self,
        user_id: UUID,
        command: ServiceLeadInput,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        return await self.create_request(
            user_id, "service", command.model_dump(mode="json"), principal
        )

    async def catalog(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        async with self.transactions.transaction() as session:
            await self.authorize(user_id, principal, session=session)
        return {
            "services": CATALOG,
            "result_required_fields": RESULT_REQUIRED,
            "consent_required": True,
            "pricing_source": "/financial/orders/policies",
        }
