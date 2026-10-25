"""Signed manual closure follows the immutable paid policy."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.native_caller_errors import NoStoreSelectionRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class CloseSelection(SignedMiniAppRequest):
    reason: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(min_length=1, max_length=4000)


def create_selection_maturity_router(resolve):
    router = APIRouter(
        prefix="/financial/orders", route_class=NoStoreSelectionRoute
    )

    @router.post("/{order_id}/selection/close")
    async def close(order_id: UUID, request: Request, body: CloseSelection):
        if request.query_params:
            raise HTTPException(422, "selection_request_invalid")
        principal = await resolve(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        if not request.app.state.config.financial.core_enabled:
            raise HTTPException(503, "financial_disabled")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get("selection_maturity_service")
        tm = dispatcher.get("transaction_manager")
        if service is None or tm is None:
            raise HTTPException(503, "selection_unavailable")
        async with tm.transaction() as session:
            return await service.refresh(
                order_id,
                session=session,
                actor_id=principal.user_id,
                principal=principal,
                reason=body.reason,
                evidence=body.evidence,
            )

    return router
