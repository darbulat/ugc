"""Authenticated creator social links for both Mini App messengers."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.social_ports import SocialEditorPort
from ugc_bot.domain.enums import WorkFormat
from ugc_bot.domain.social import SocialAccount, SocialPlatform
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest
from ugc_bot.miniapp.social_errors import NoStoreSocialRoute


class AccountListRequest(SignedMiniAppRequest):
    skipped: list[SocialPlatform] = Field(default_factory=list, max_length=5)
    include_vk: bool = False


class AccountSaveRequest(SignedMiniAppRequest):
    network: SocialPlatform
    url: str = Field(min_length=1, max_length=2048)
    work_format: WorkFormat | None = None


class AccountRemoveRequest(SignedMiniAppRequest):
    account_id: UUID


class AccountsResponse(BaseModel):
    accounts: list[SocialAccount]
    next_platform: SocialPlatform | None


class AccountSavedResponse(BaseModel):
    account: SocialAccount
    next_platform: SocialPlatform | None


class AccountRemovedResponse(BaseModel):
    removed: bool


def create_social_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/social", route_class=NoStoreSocialRoute)

    async def context(
        request: Request, body: SignedMiniAppRequest
    ) -> tuple[AuthenticatedMessengerPrincipal, SocialEditorPort]:
        if request.query_params:
            raise HTTPException(422, "social_request_invalid")
        principal = await resolve_principal(
            request, body.init_data, platform=body.platform
        )
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.platform != body.platform
        ):
            raise HTTPException(401, "financial_session_invalid")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get("social_account_service")
        if service is None:
            raise HTTPException(status_code=503, detail="social_unavailable")
        return principal, cast(SocialEditorPort, service)

    @router.post("/accounts")
    async def accounts(
        request: Request, body: AccountListRequest
    ) -> AccountsResponse:
        principal, service = await context(request, body)
        state = await service.editor_state(
            principal.user_id,
            principal=principal,
            skipped=body.skipped,
            include_vk=body.include_vk,
        )
        return AccountsResponse(
            accounts=list(state.accounts),
            next_platform=state.next_platform,
        )

    @router.post("/accounts/save")
    async def save_account(
        request: Request, body: AccountSaveRequest
    ) -> AccountSavedResponse:
        principal, service = await context(request, body)
        saved = await service.save_editor_account(
            principal.user_id,
            body.network,
            body.url,
            principal=principal,
            work_format=body.work_format,
        )
        return AccountSavedResponse(
            account=saved.account,
            next_platform=saved.next_platform,
        )

    @router.post("/accounts/remove")
    async def remove_account(
        request: Request, body: AccountRemoveRequest
    ) -> AccountRemovedResponse:
        principal, service = await context(request, body)
        removed = await service.remove_editor_account(
            principal.user_id,
            body.account_id,
            principal=principal,
        )
        return AccountRemovedResponse(removed=removed)

    return router
