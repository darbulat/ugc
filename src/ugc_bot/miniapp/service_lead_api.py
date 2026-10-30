"""Signed typed inquiries and shared service catalog."""

from fastapi import APIRouter, Request

from ugc_bot.domain.customer_workflows import ServiceLeadInput
from ugc_bot.miniapp.customer_workflow_api import CustomerWorkflowRoute, context
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class ServiceLeadRequest(SignedMiniAppRequest, ServiceLeadInput):
    pass


def create_service_lead_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/customer/services", route_class=CustomerWorkflowRoute
    )

    @router.post("")
    async def create(request: Request, body: ServiceLeadRequest):
        principal, service = await context(
            request, body, resolve, "service_lead_service"
        )
        return await service.create(
            principal.user_id,
            ServiceLeadInput(
                **body.model_dump(exclude={"init_data", "platform"})
            ),
            principal=principal,
        )

    @router.post("/catalog")
    async def catalog(request: Request, body: SignedMiniAppRequest):
        principal, service = await context(
            request, body, resolve, "service_lead_service"
        )
        return await service.catalog(principal.user_id, principal=principal)

    return router
