"""Signed meaningful activity and opt-out; payment events stay server-only."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request

from ugc_bot.miniapp.customer_workflow_api import CustomerWorkflowRoute, context
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class FollowupActivity(SignedMiniAppRequest):
    event: Literal["menu", "brief_opened", "brief_changed", "order_created"]
    order_id: UUID | None = None
    intent_id: UUID | None = None


def create_client_followup_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/customer/followups", route_class=CustomerWorkflowRoute
    )

    @router.post("/activity")
    async def activity(request: Request, body: FollowupActivity):
        principal, service = await context(
            request, body, resolve, "client_followup_service"
        )
        return await service.record_activity(
            principal.user_id,
            body.event,
            body.order_id,
            principal=principal,
            intent_id=body.intent_id,
        )

    @router.post("/state")
    async def state(request: Request, body: SignedMiniAppRequest):
        principal, service = await context(
            request, body, resolve, "client_followup_service"
        )
        return await service.state(principal.user_id, principal=principal)

    @router.post("/optout")
    async def optout(request: Request, body: SignedMiniAppRequest):
        principal, service = await context(
            request, body, resolve, "client_followup_service"
        )
        await service.optout(principal.user_id, principal=principal)
        return {"opted_out": True}

    return router
