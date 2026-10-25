"""Signed own reports and approved-recipient actions, without contacts."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.campaign_moderation_api import (
    NoStoreCampaignModerationRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class CampaignTarget(SignedMiniAppRequest):
    campaign_id: UUID


class CampaignResponse(CampaignTarget):
    operation_key: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=0, strict=True)
    choice: Literal["interested", "declined", "withdrawn"]


def create_campaign_runtime_router(resolve):
    router = APIRouter(
        prefix="/campaigns", route_class=NoStoreCampaignModerationRoute
    )

    async def invoke(request, body, action):
        if request.query_params:
            raise HTTPException(422, "campaign_request_invalid")
        principal = await resolve(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "campaign_session_invalid")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get("campaign_response_service")
        tm = dispatcher.get("transaction_manager")
        if service is None or tm is None:
            raise HTTPException(503, "campaign_moderation_unavailable")
        async with tm.transaction() as session:
            values = {"principal": principal, "session": session}
            if action == "respond":
                values.update(
                    operation_key=body.operation_key,
                    expected_version=body.expected_version,
                    choice=body.choice,
                )
            return await getattr(service, action)(
                principal.user_id, body.campaign_id, **values
            )

    @router.post("/recipient/view")
    async def recipient(request: Request, body: CampaignTarget):
        return await invoke(request, body, "view")

    @router.post("/recipient/respond")
    async def respond(request: Request, body: CampaignResponse):
        return await invoke(request, body, "respond")

    @router.post("/owned/report")
    async def report(request: Request, body: CampaignTarget):
        return await invoke(request, body, "report")

    return router
