"""Signed own-only partner reads remain available while money writes pause."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStorePartnerRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class PartnerReadRequest(SignedMiniAppRequest):
    network_page: int = Field(default=0, ge=0, le=100000, strict=True)
    history_page: int = Field(default=0, ge=0, le=100000, strict=True)
    assignment_page: int = Field(default=0, ge=0, le=100000, strict=True)


def create_partner_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/partner", route_class=NoStorePartnerRoute)

    @router.post("/view")
    async def view(request: Request, body: PartnerReadRequest):
        if request.query_params:
            raise HTTPException(422, "partner_request_invalid")
        principal = await resolve_principal(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get("partner_view_service")
        transactions = dispatcher.get("transaction_manager")
        if service is None or transactions is None:
            raise HTTPException(503, "partner_unavailable")
        paused = not request.app.state.config.financial.core_enabled
        try:
            async with transactions.transaction() as session:
                return await service.view(
                    principal.user_id,
                    platform=body.platform,
                    network_page=body.network_page,
                    history_page=body.history_page,
                    assignment_page=body.assignment_page,
                    writes_paused=paused,
                    session=session,
                    principal=principal,
                )
        except LookupError as exc:
            if str(exc) == "partner_not_found":
                raise HTTPException(404, "partner_not_found") from None
            raise

    return router
