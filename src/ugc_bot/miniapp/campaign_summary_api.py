"""Signed own-order summaries; no client-selected recipient or outcome."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreSummaryRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


def create_campaign_summary_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/orders", route_class=NoStoreSummaryRoute)

    @router.post("/{order_id}/campaign-summary")
    async def view(
        order_id: UUID, request: Request, body: SignedMiniAppRequest
    ):
        if request.query_params:
            raise HTTPException(422, "summary_request_invalid")
        principal = await resolve(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        service = request.app.state.dispatcher.get("campaign_summary_service")
        if service is None:
            raise HTTPException(503, "summary_unavailable")
        try:
            return await service.view(
                order_id, principal.user_id, principal=principal
            )
        except LookupError as exc:
            if str(exc) == "summary_not_found":
                raise HTTPException(404, "summary_not_found") from None
            raise

    return router
