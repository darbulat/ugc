"""Signed, scope-derived replacement review and contact disclosure commands."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.replacement_ports import (
    ReplacementContact,
    ReplacementDecision,
    ReplacementRequest,
)
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class ReplacementRoute(_NativeCallerRoute):
    prefix = "replacement"
    codes = SHARED_CODES | {
        "active_admin_required": 403,
        "replacement_forbidden": 403,
        "financial_core_paused": 503,
        "replacement_position_not_found": 404,
        "replacement_request_not_found": 404,
        "replacement_allocation_not_found": 404,
        **{
            code: 409
            for code in (
                "replacement_paid_capture_required",
                "replacement_current_assignment_required",
                "replacement_assignment_version_conflict",
                "replacement_after_completed_work_forbidden",
                "replacement_position_unavailable",
                "replacement_fact_in_future",
                "replacement_source_changed",
                "replacement_confirmed_reserve_required",
                "replacement_request_already_reviewed",
                "replacement_request_version_conflict",
                "replacement_reserve_exception_required",
                "replacement_active_manager_required",
                "replacement_original_ground_mismatch",
                "replacement_assignment_obsolete",
                "replacement_contact_unavailable",
                "replacement_paid_ground_review_required",
                "correction_reserved_review_required",
            )
        },
        **{
            code: 422
            for code in (
                "replacement_identity_required",
                "replacement_reason_evidence_required",
                "replacement_operation_key_required",
                "replacement_assignment_version_required",
                "replacement_reason_code_invalid",
                "replacement_request_version_required",
                "replacement_action_invalid",
            )
        },
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class ReplacementViewRequest(SignedMiniAppRequest):
    paid_item_id: UUID


class ReplacementQueueRequest(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)


class ReplacementRequestBody(ReplacementViewRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    expected_assignment_version: int = Field(ge=1, strict=True)
    candidate_interest_id: UUID
    reason_code: Literal["refusal", "lost_contact", "brief_mismatch"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)


class ReplacementDecisionBody(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    request_id: UUID
    expected_version: int = Field(ge=1, le=1, strict=True)
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    manager_id: UUID | None = None
    exception_reason: str | None = Field(
        default=None, min_length=1, max_length=4000
    )
    exception_evidence: str | None = Field(
        default=None, min_length=1, max_length=4000
    )


class ReplacementContactBody(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    replacement_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)


async def _context(resolve_principal, request, body):
    if request.query_params:
        raise HTTPException(422, "replacement_request_invalid")
    principal = await resolve_principal(
        request, body.init_data, platform=body.platform
    )
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    services = request.app.state.dispatcher
    service, transactions = (
        services.get("replacement_service"),
        services.get("transaction_manager"),
    )
    if service is None or transactions is None:
        raise HTTPException(503, "replacement_unavailable")
    return principal, service, transactions


def create_replacement_router(resolve_principal):
    router = APIRouter(
        prefix="/financial/replacements", route_class=ReplacementRoute
    )

    async def context(request, body):
        return await _context(resolve_principal, request, body)

    @router.post("/view")
    async def view(request: Request, body: ReplacementViewRequest):
        principal, service, transactions = await context(request, body)
        async with transactions.transaction() as session:
            return await service.view(
                principal.user_id,
                body.paid_item_id,
                principal=principal,
                session=session,
            )

    @router.post("/queue")
    async def queue(request: Request, body: ReplacementQueueRequest):
        principal, service, transactions = await context(request, body)
        async with transactions.transaction() as session:
            return await service.queue(
                principal.user_id,
                page=body.page,
                principal=principal,
                session=session,
            )

    async def execute(request, body, command_type, method):
        principal, service, transactions = await context(request, body)
        command = command_type(
            actor_id=principal.user_id,
            **body.model_dump(exclude={"init_data", "platform"}),
        )
        async with transactions.transaction() as session:
            return await getattr(service, method)(
                command, principal=principal, session=session
            )

    @router.post("/request")
    async def submit(request: Request, body: ReplacementRequestBody):
        return await execute(request, body, ReplacementRequest, "request")

    @router.post("/decision")
    async def decide(request: Request, body: ReplacementDecisionBody):
        return await execute(request, body, ReplacementDecision, "decide")

    @router.post("/contact")
    async def contact(request: Request, body: ReplacementContactBody):
        return await execute(request, body, ReplacementContact, "contact")

    return router
