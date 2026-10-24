"""Signed administrative rate changes with server-owned approval authority."""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.override_ports import (
    CreateRateOverride,
    OverrideCommandResult,
    OverrideState,
    RevokeRateOverride,
    SupersedeRateOverride,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.rate_override_service import (
    RateOverrideService,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest

PUBLIC_OVERRIDE_CODES = frozenset(
    {
        "active_admin_required",
        "financial_principal_changed",
        "typed_override_command_required",
        "idempotency_payload_conflict",
        "override_recipient_not_found",
        "approved_policy_required",
        "override_backdating_forbidden",
        "override_not_found",
        "override_scope_mismatch",
        "override_version_conflict",
        "override_already_revoked",
        "override_change_outside_period",
        "override_period_overlaps",
        "invalid_override_side",
        "override_identity_required",
        "override_provenance_required",
        "aware_timestamp_required",
        "invalid_override_rate",
        "invalid_override_period",
        "override_expected_version_required",
    }
)


PUBLIC_OVERRIDE_HTTP_CODES = PUBLIC_OVERRIDE_CODES | frozenset(
    {
        "override_request_invalid",
        "override_unavailable",
        "financial_core_disabled",
        "financial_session_invalid",
        "existing_financial_account_required",
        "financial_unavailable",
    }
)


class NoStoreOverrideRoute(APIRoute):
    """Keep signed inputs and unexpected exception details out of responses."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "override_request_invalid"}, status_code=422
                )
            except HTTPException as error:
                if (
                    not isinstance(error.detail, str)
                    or error.detail not in PUBLIC_OVERRIDE_HTTP_CODES
                ):
                    raise HTTPException(
                        503,
                        "override_unavailable",
                        headers={"Cache-Control": "no-store"},
                    ) from None
                error.headers = {
                    **(error.headers or {}),
                    "Cache-Control": "no-store",
                }
                raise
            except Exception:
                raise HTTPException(
                    503,
                    "override_unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class OverrideScopeRequest(SignedMiniAppRequest):
    recipient_id: UUID
    side: Literal["client", "creator"]
    policy_version: str = Field(min_length=1, max_length=256)


class OverrideCommandRequest(OverrideScopeRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=4000)


class OverrideRateRequest(OverrideCommandRequest):
    rate_bps: int = Field(ge=1, le=10000, strict=True)
    effective_from: AwareDatetime
    effective_until: AwareDatetime


class CreateOverrideRequest(OverrideRateRequest):
    action: Literal["create"]


class RevokeOverrideRequest(OverrideCommandRequest):
    action: Literal["revoke"]
    override_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    effective_at: AwareDatetime


class SupersedeOverrideRequest(OverrideRateRequest):
    action: Literal["supersede"]
    override_id: UUID
    expected_version: int = Field(ge=1, strict=True)


OverrideInput = Annotated[
    CreateOverrideRequest | RevokeOverrideRequest | SupersedeOverrideRequest,
    Field(discriminator="action"),
]


async def _context(
    request: Request,
    body: SignedMiniAppRequest,
    resolve: FinancialPrincipalResolver,
) -> tuple[
    AuthenticatedMessengerPrincipal, RateOverrideService, TransactionManager
]:
    if request.query_params:
        raise HTTPException(422, "override_request_invalid")
    actor_id = await resolve(request, body.init_data, platform=body.platform)
    if not isinstance(actor_id, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    if not request.app.state.config.financial.core_enabled:
        raise HTTPException(status_code=503, detail="financial_core_disabled")
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("rate_override_service")
    transactions = dispatcher.get("transaction_manager")
    if service is None or transactions is None:
        raise HTTPException(status_code=503, detail="override_unavailable")
    return (
        actor_id,
        cast(RateOverrideService, service),
        cast(TransactionManager, transactions),
    )


def _error(error: ValueError) -> HTTPException:
    code = str(error)
    code = code if code in PUBLIC_OVERRIDE_CODES else "override_unavailable"
    return HTTPException(
        status_code=503
        if code == "override_unavailable"
        else 403
        if code in ("active_admin_required", "financial_principal_changed")
        else 409,
        detail=code,
    )


def create_override_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/admin/rate-overrides", route_class=NoStoreOverrideRoute
    )

    @router.post("/command")
    async def command(
        request: Request,
        body: OverrideInput,
    ) -> OverrideCommandResult:
        actor_id, service, transactions = await _context(
            request, body, resolve_principal
        )
        constructors = {
            "create": CreateRateOverride,
            "revoke": RevokeRateOverride,
            "supersede": SupersedeRateOverride,
        }
        try:
            value = constructors[body.action](
                actor_id=actor_id.user_id,
                **body.model_dump(exclude={"init_data", "platform", "action"}),
            )
            async with transactions.transaction() as session:
                return await service.execute(
                    value, session=session, principal=actor_id
                )
        except ValueError as error:
            raise _error(error) from None

    @router.post("/list")
    async def list_scope(
        request: Request,
        body: OverrideScopeRequest,
    ) -> tuple[OverrideState, ...]:
        actor_id, service, transactions = await _context(
            request, body, resolve_principal
        )
        try:
            async with transactions.transaction() as session:
                return await service.list_for_admin(
                    body.recipient_id,
                    body.side,
                    body.policy_version,
                    actor_id=actor_id.user_id,
                    session=session,
                    principal=actor_id,
                )
        except ValueError as error:
            raise _error(error) from None

    @router.post("/{override_id}/status")
    async def status(
        request: Request,
        override_id: UUID,
        body: SignedMiniAppRequest,
    ) -> OverrideState:
        actor_id, service, transactions = await _context(
            request, body, resolve_principal
        )
        try:
            async with transactions.transaction() as session:
                value = await service.get_for_admin(
                    override_id,
                    actor_id=actor_id.user_id,
                    session=session,
                    principal=actor_id,
                )
        except ValueError as error:
            raise _error(error) from None
        if value is None:
            raise HTTPException(status_code=404, detail="override_not_found")
        return value

    return router
