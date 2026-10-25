"""Explicit superadmin positive adjustments; no payment or tax automation."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BeforeValidator, Field

from ugc_bot.application.manual_grant_ports import ApproveManualGrant
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.correction_wire import (
    correction_to_wire,
    parse_observed_minor,
)
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class ManualGrantRoute(_NativeCallerRoute):
    prefix = "manual_grant"
    codes = SHARED_CODES | {
        "financial_superadmin_required": 403,
        "active_admin_required": 403,
        "financial_core_disabled": 503,
        "manual_grant_not_found": 404,
        "manual_grant_recipient_unavailable": 409,
        "manual_grant_before_capture": 409,
        "manual_grant_source_mismatch": 409,
        "financial_scope_changed_retry_required": 409,
        "manual_grant_obligation_missing": 409,
        "manual_grant_capture_required": 409,
        "capture_funding_missing": 409,
        "correction_unresolved": 409,
        "correction_component_refunded": 409,
        "work_disputed": 409,
        "reconciliation_mismatch_audit_required": 409,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class Approve(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    paid_item_id: UUID
    recipient_id: UUID
    amount_minor: Annotated[int, BeforeValidator(parse_observed_minor)] = Field(
        gt=0
    )
    currency: Literal["RUB"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Mature(SignedMiniAppRequest):
    grant_id: UUID


async def _principal(resolve, request, body):
    if request.query_params:
        raise HTTPException(422, "manual_grant_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != body.platform
    ):
        raise HTTPException(401, "financial_session_invalid")
    return principal


async def _invoke(resolve, request, body, action):
    principal = await _principal(resolve, request, body)
    services = request.app.state.dispatcher
    transaction = getattr(
        services.get("transaction_manager"), "transaction", None
    )
    service = services.get("manual_grant_service")
    if service is None or not callable(transaction):
        raise HTTPException(503, "financial_unavailable")
    if (
        action != "context"
        and not request.app.state.config.financial.core_enabled
    ):
        raise HTTPException(503, "financial_core_disabled")
    async with transaction() as session:
        if session is None:
            raise HTTPException(503, "financial_unavailable")
        admins = services.get("partner_admin_service")
        if admins is None:
            raise HTTPException(503, "financial_unavailable")
        await admins.context(
            principal.user_id, principal=principal, session=session
        )
        enabled = request.app.state.config.financial.core_enabled
        allowed = principal.user_id in service.superadmins
        if action != "context" and not allowed:
            raise HTTPException(403, "financial_superadmin_required")
        if action == "context":
            result = {
                "actor_id": str(principal.user_id),
                "can_approve": allowed and enabled,
                "can_mature": allowed and enabled,
                "writes_paused": not enabled,
            }
            return jsonable_encoder(correction_to_wire(result))
    # The authority transaction releases its actor lock. The service then
    # reacquires all current actors in canonical order and rechecks authority.
    async with transaction() as session:
        if session is None:
            raise HTTPException(503, "financial_unavailable")
        if action == "approve":
            command = ApproveManualGrant(
                actor_id=principal.user_id,
                **body.model_dump(exclude={"init_data", "platform"}),
            )
            result = await service.approve(
                command, principal=principal, session=session
            )
        else:
            result = await service.mature(
                body.grant_id,
                actor_id=principal.user_id,
                principal=principal,
                session=session,
            )
        return jsonable_encoder(correction_to_wire(result))


def create_manual_grant_router(resolve):
    router = APIRouter(
        prefix="/financial/grants/admin", route_class=ManualGrantRoute
    )

    @router.post("/context")
    async def context(request: Request, body: SignedMiniAppRequest):
        return await _invoke(resolve, request, body, "context")

    @router.post("/approve")
    async def approve(request: Request, body: Approve):
        return await _invoke(resolve, request, body, "approve")

    @router.post("/mature")
    async def mature(request: Request, body: Mature):
        return await _invoke(resolve, request, body, "mature")

    return router
