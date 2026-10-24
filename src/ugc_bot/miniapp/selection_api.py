"""Only signed own-client reads; no public provider outcome authority."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreSelectionRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


def create_selection_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/financial/orders", route_class=NoStoreSelectionRoute
    )

    @router.post("/{order_id}/selection")
    async def view(
        order_id: UUID, request: Request, body: SignedMiniAppRequest
    ):
        if request.query_params:
            raise HTTPException(422, "selection_request_invalid")
        principal = await resolve_principal(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        service = request.app.state.dispatcher.get("selection_view_service")
        if service is None:
            raise HTTPException(503, "selection_unavailable")
        try:
            result = await service.view(
                order_id, principal.user_id, principal=principal
            )
            paused = not request.app.state.config.financial.core_enabled
            return dict(result, writes_paused=paused)
        except LookupError as exc:
            if str(exc) == "selection_order_not_found":
                raise HTTPException(404, "selection_order_not_found") from None
            raise

    return router
