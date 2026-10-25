"""Signed admin review of real grounds after any work window."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BeforeValidator, Field

from ugc_bot.application.financial_review_ports import (
    OpenFinancialReview,
    ResolveFinancialReview,
)
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


class ReviewRoute(_NativeCallerRoute):
    prefix = "financial_review"
    codes = SHARED_CODES | {
        "active_admin_required": 403,
        "correction_provenance_required": 422,
        "correction_hash_invalid": 422,
        "correction_identity_invalid": 422,
        "correction_minor_invalid": 422,
        "correction_version_invalid": 422,
        "financial_review_active_admin_required": 403,
        "financial_review_ground_not_found": 404,
        "financial_review_case_not_found": 404,
        "financial_review_time_conflict": 409,
        "financial_review_no_liability": 409,
        "financial_review_blocked_source_changed": 409,
        "financial_review_invalid_page": 409,
        "financial_review_decision_invalid": 409,
        "financial_scope_changed_retry_required": 409,
        "financial_core_disabled": 503,
        "financial_review_not_found": 404,
        "financial_review_source_required": 409,
        "financial_review_source_changed": 409,
        "financial_review_version_conflict": 409,
        "financial_review_already_open": 409,
        "financial_review_already_resolved": 409,
        "correction_cumulative_target_invalid": 409,
        "correction_reserved_review_required": 409,
        "reconciliation_mismatch_audit_required": 409,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


def parse_target_minor(value):
    return None if value is None else parse_observed_minor(value)


class Context(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=25, ge=1, le=100, strict=True)
    business_key: str | None = Field(
        default=None, min_length=1, max_length=4000
    )


class Evidence(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Open(Evidence):
    business_key: str = Field(min_length=1, max_length=4000)


class Resolve(Evidence):
    case_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    decision: Literal["no_adjustment", "cumulative_cancel"]
    target_minor: Annotated[int | None, BeforeValidator(parse_target_minor)] = (
        Field(default=None, ge=0)
    )


def _wire(value):
    if isinstance(value, dict):
        result = {key: _wire(item) for key, item in value.items()}
        if "buckets" in result and isinstance(result["buckets"], dict):
            result["buckets"] = {
                key: str(item) if type(item) is int else item
                for key, item in result["buckets"].items()
            }
        return correction_to_wire(result)
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


async def _principal(resolve, request, body):
    if request.query_params:
        raise HTTPException(422, "financial_review_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != body.platform
    ):
        raise HTTPException(401, "financial_session_invalid")
    return principal


async def _admin(services, transaction, principal):
    admins = services.get("partner_admin_service")
    if admins is None:
        raise HTTPException(503, "financial_unavailable")
    async with transaction() as session:
        if session is None:
            raise HTTPException(503, "financial_unavailable")
        await admins.context(
            principal.user_id, principal=principal, session=session
        )


class FinancialReviewApi:
    def __init__(self, resolve):
        self.resolve = resolve

    async def invoke(
        self, request, body, method, constructor=None, case_id=None
    ):
        principal = await _principal(self.resolve, request, body)
        services = request.app.state.dispatcher
        transaction = getattr(
            services.get("transaction_manager"), "transaction", None
        )
        service = services.get("financial_review_service")
        if service is None or not callable(transaction):
            raise HTTPException(503, "financial_unavailable")
        paused = not request.app.state.config.financial.core_enabled
        if constructor is not None and paused:
            raise HTTPException(503, "financial_core_disabled")
        # Release the early actor lock before the service locks its complete
        # canonical scope and checks the current admin authority again.
        await _admin(services, transaction, principal)
        values = body.model_dump(exclude={"init_data", "platform"})
        async with transaction() as session:
            if session is None:
                raise HTTPException(503, "financial_unavailable")
            if constructor is not None:
                result = await getattr(service, method)(
                    constructor(actor_id=principal.user_id, **values),
                    principal=principal,
                    session=session,
                )
            elif case_id is not None:
                result = await service.view(
                    principal.user_id,
                    case_id,
                    principal=principal,
                    session=session,
                )
                if result is None:
                    raise HTTPException(404, "financial_review_not_found")
            else:
                result = await service.context(
                    principal.user_id,
                    principal=principal,
                    session=session,
                    **values,
                )
                result = dict(
                    result,
                    actor_id=str(principal.user_id),
                    writes_paused=paused,
                )
            return jsonable_encoder(_wire(result))


def create_financial_review_router(resolve):
    router = APIRouter(
        prefix="/financial/reviews/admin", route_class=ReviewRoute
    )
    api = FinancialReviewApi(resolve)

    @router.post("/context")
    async def context(request: Request, body: Context):
        return await api.invoke(request, body, "context")

    @router.post("/{case_id}/view")
    async def view(request: Request, case_id: UUID, body: SignedMiniAppRequest):
        return await api.invoke(request, body, "view", case_id=case_id)

    @router.post("/open")
    async def open_review(request: Request, body: Open):
        return await api.invoke(request, body, "open", OpenFinancialReview)

    @router.post("/resolve")
    async def resolve_review(request: Request, body: Resolve):
        return await api.invoke(
            request, body, "resolve", ResolveFinancialReview
        )

    return router
