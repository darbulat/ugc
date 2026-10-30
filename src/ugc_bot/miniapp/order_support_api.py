"""Signed owner support endpoints; endpoints never call repositories."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request

from ugc_bot.domain.customer_workflows import SupportInput
from ugc_bot.miniapp.customer_workflow_api import CustomerWorkflowRoute, context
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class SupportRequest(SignedMiniAppRequest, SupportInput):
    pass


class SupportList(SignedMiniAppRequest):
    order_id: UUID


class SupportStatus(SignedMiniAppRequest):
    request_id: UUID
    state: Literal["new", "in_progress", "resolved"]


def create_order_support_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/customer/support", route_class=CustomerWorkflowRoute
    )

    @router.post("")
    async def create(request: Request, body: SupportRequest):
        principal, service = await context(
            request, body, resolve, "order_support_service"
        )
        return await service.create(
            principal.user_id,
            SupportInput(**body.model_dump(exclude={"init_data", "platform"})),
            principal=principal,
        )

    @router.post("/list")
    async def listing(request: Request, body: SupportList):
        principal, service = await context(
            request, body, resolve, "order_support_service"
        )
        return {
            "requests": await service.list(
                principal.user_id, body.order_id, principal=principal
            )
        }

    @router.post("/status")
    async def status(request: Request, body: SupportStatus):
        principal, service = await context(
            request, body, resolve, "order_support_service"
        )
        await service.update_status(
            principal.user_id, body.request_id, body.state, principal=principal
        )
        return {"state": body.state}

    return router
