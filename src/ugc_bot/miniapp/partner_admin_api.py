"""Signed operational lead decisions and audited referral attachment repair."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.partner_admin_ports import (
    BindingCorrectionCommand,
    LeadReviewCommand,
)
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class PartnerAdminRoute(_NativeCallerRoute):
    prefix = "partner_admin"
    codes = SHARED_CODES | {
        "active_admin_required": 403,
        "active_manager_required": 409,
        "lead_not_found": 404,
        "lead_version_conflict": 409,
        "lead_already_reviewed": 409,
        "lead_review_managers_invalid": 422,
        "lead_review_action_invalid": 422,
        "lead_version_required": 422,
        "admin_review_reason_required": 422,
        "admin_review_identity_required": 422,
        "lead_queue_invalid": 422,
        "self_referral_forbidden": 409,
        "referral_user_not_found": 404,
        "active_referrer_required": 409,
        "referral_binding_changed": 409,
        "referral_binding_unchanged": 409,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class LeadQueueRequest(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)
    status: Literal["pending", "accepted", "rejected", "all"] = "pending"


class LeadReviewRequest(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    lead_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    action: Literal["accept", "reject"]
    manager_ids: list[UUID] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=4000)


class BindingCorrectionRequest(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    referred_id: UUID
    expected_referrer_id: UUID
    referrer_id: UUID
    reason: str = Field(min_length=1, max_length=4000)


def create_partner_admin_router(resolve_principal):
    router = APIRouter(prefix="/admin/partners", route_class=PartnerAdminRoute)

    async def context(request, body):
        if request.query_params:
            raise HTTPException(422, "partner_admin_request_invalid")
        principal = await resolve_principal(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        services = request.app.state.dispatcher
        service, transactions = (
            services.get("partner_admin_service"),
            services.get("transaction_manager"),
        )
        if service is None or transactions is None:
            raise HTTPException(503, "partner_admin_unavailable")
        return principal, service, transactions

    @router.post("/context")
    async def own_context(request: Request, body: SignedMiniAppRequest):
        principal, service, transactions = await context(request, body)
        async with transactions.transaction() as session:
            return await service.context(
                principal.user_id, principal=principal, session=session
            )

    @router.post("/leads")
    async def leads(request: Request, body: LeadQueueRequest):
        principal, service, transactions = await context(request, body)
        async with transactions.transaction() as session:
            return await service.queue(
                principal.user_id,
                principal=principal,
                page=body.page,
                status=body.status,
                session=session,
            )

    @router.post("/lead-command")
    async def lead_command(request: Request, body: LeadReviewRequest):
        principal, service, transactions = await context(request, body)
        values = body.model_dump(
            exclude={"init_data", "platform", "manager_ids"}
        )
        command = LeadReviewCommand(
            actor_id=principal.user_id,
            manager_ids=tuple(body.manager_ids),
            **values,
        )
        async with transactions.transaction() as session:
            return await service.review_lead(
                command, principal=principal, session=session
            )

    @router.post("/binding-command")
    async def binding_command(request: Request, body: BindingCorrectionRequest):
        principal, service, transactions = await context(request, body)
        command = BindingCorrectionCommand(
            actor_id=principal.user_id,
            **body.model_dump(exclude={"init_data", "platform"}),
        )
        async with transactions.transaction() as session:
            return await service.correct_binding(
                command, principal=principal, session=session
            )

    return router
