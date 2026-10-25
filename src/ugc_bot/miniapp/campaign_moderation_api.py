"""Signed moderation HTTP; delivery runs separately after committed approval."""

from types import MappingProxyType
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.campaign_moderation import (
    CancelCampaign,
    ReviewCampaign,
    SettleCampaignExpiry,
    SubmitCampaign,
)
from ugc_bot.miniapp.campaign_principal import CampaignPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest

UNAVAILABLE = "campaign_moderation_unavailable"
PUBLIC_ERRORS = MappingProxyType(
    {
        "campaign_session_invalid": 401,
        **dict.fromkeys(
            (
                "campaign_principal_changed",
                "campaign_active_actor_required",
                "campaign_current_admin_required",
                "campaign_current_publisher_required",
                "campaign_current_policy_required",
                "campaign_distinct_admin_required",
                "campaign_owner_required",
                "campaign_recipient_no_longer_eligible",
                "campaign_subscription_required",
                "campaign_subscription_quota_exceeded",
            ),
            403,
        ),
        **dict.fromkeys(
            (
                "existing_campaign_account_required",
                "campaign_draft_not_found",
                "campaign_submission_not_found",
            ),
            404,
        ),
        **dict.fromkeys(
            (
                "campaign_terms_changed",
                "campaign_publisher_changed",
                "campaign_revision_changed",
                "campaign_version_conflict",
                "campaign_operation_conflict",
                "campaign_scope_changed",
                "campaign_review_context_changed",
                "campaign_review_expired",
                "campaign_policy_changed",
                "campaign_capacity_exceeded",
                "campaign_capacity_settlement_required",
                "campaign_empty_audience",
                "campaign_not_active",
                "campaign_not_submitted",
            ),
            409,
        ),
        **dict.fromkeys(
            (
                "campaign_request_invalid",
                "campaign_invalid_page",
                "campaign_content_limit_exceeded",
            ),
            422,
        ),
        **dict.fromkeys(
            (
                UNAVAILABLE,
                "campaign_unavailable",
                "campaign_capacity_unavailable",
                "campaign_capacity_integrity_unavailable",
                "campaign_audience_integrity_unavailable",
                "campaign_expiry_facts_unavailable",
                "campaign_receipt_unavailable",
                "campaign_state_unavailable",
                "campaign_read_context_unavailable",
                "campaign_caller_transaction_required",
                "campaign_submission_integrity_unavailable",
                "campaign_review_authority_unavailable",
                "campaign_content_limits_required",
            ),
            503,
        ),
    }
)


def _failure(code: object) -> JSONResponse:
    safe = code if type(code) is str and code in PUBLIC_ERRORS else UNAVAILABLE
    return JSONResponse({"detail": safe}, status_code=PUBLIC_ERRORS[safe])


class NoStoreCampaignModerationRoute(APIRoute):
    """Cover parsing, identity, dependencies, transaction and serialization."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = _failure("campaign_request_invalid")
            except HTTPException as error:
                response = _failure(error.detail)
            except (PermissionError, LookupError, ValueError) as error:
                # Do not stringify private/unexpected exception values.
                response = _failure(
                    error.args[0] if len(error.args) == 1 else None
                )
            except Exception:
                response = _failure(UNAVAILABLE)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class CampaignOperation(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256, strict=True)


class CampaignTarget(CampaignOperation):
    campaign_id: UUID
    expected_version: int = Field(ge=1, strict=True)


class SubmitRequest(CampaignTarget):
    revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    policy_version: int = Field(ge=1, strict=True)
    terms_hash: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


class CancelRequest(CampaignTarget):
    reason: str = Field(min_length=1, max_length=1000, strict=True)


class DecisionRequest(CancelRequest):
    submission_id: UUID
    revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    review_context: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)


class QueueRequest(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)


class ReviewRequest(SignedMiniAppRequest):
    submission_id: UUID


class SettleRequest(CampaignOperation):
    expected_policy_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000, strict=True)


_COMMANDS: dict[
    str,
    type[SubmitCampaign]
    | type[CancelCampaign]
    | type[ReviewCampaign]
    | type[SettleCampaignExpiry],
] = {
    "submit": SubmitCampaign,
    "cancel": CancelCampaign,
    "approve": ReviewCampaign,
    "reject": ReviewCampaign,
    "settle": SettleCampaignExpiry,
}
_CALLS = {
    "submit": ("campaign_submission_service", "submit"),
    "cancel": ("campaign_moderation_service", "cancel"),
    "queue": ("campaign_moderation_service", "queue"),
    "review": ("campaign_moderation_service", "review_detail"),
    "approve": ("campaign_moderation_service", "decide"),
    "reject": ("campaign_moderation_service", "decide"),
    "settle": ("campaign_capacity_service", "settle_expired"),
}


def _arguments(action: str, body: Any, actor: UUID) -> tuple:
    if action == "queue":
        return actor, body.page
    if action == "review":
        return actor, body.submission_id
    payload = body.model_dump(exclude={"init_data", "platform"}, mode="json")
    if action in ("approve", "reject"):
        payload["decision"] = action
    try:
        return (_COMMANDS[action].parse(actor, payload),)
    except (ValueError, TypeError):
        raise HTTPException(422, "campaign_request_invalid") from None


async def _invoke(
    resolve: CampaignPrincipalResolver, request: Request, body: Any, action: str
) -> JSONResponse:
    if request.query_params:
        raise HTTPException(422, "campaign_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != body.platform
    ):
        raise HTTPException(401, "campaign_session_invalid")
    arguments = _arguments(action, body, principal.user_id)
    dispatcher = request.app.state.dispatcher
    service_name, method_name = _CALLS[action]
    method = getattr(dispatcher.get(service_name), method_name, None)
    transaction = getattr(
        dispatcher.get("transaction_manager"), "transaction", None
    )
    if not callable(method) or not callable(transaction):
        raise HTTPException(503, UNAVAILABLE)
    async with transaction() as session:
        if session is None:
            raise HTTPException(503, UNAVAILABLE)
        result = await method(*arguments, principal=principal, session=session)
        if type(result) is not dict:
            raise HTTPException(503, UNAVAILABLE)
        # Serialize before leaving the caller transaction, within the route's
        # exact-code boundary. Invalid encodings cannot become positive stubs.
        return JSONResponse(jsonable_encoder(result))


def create_campaign_moderation_router(
    resolve: CampaignPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/campaigns", route_class=NoStoreCampaignModerationRoute
    )

    @router.post("/owned/submit")
    async def submit(request: Request, body: SubmitRequest):
        return await _invoke(resolve, request, body, "submit")

    @router.post("/owned/cancel")
    async def cancel(request: Request, body: CancelRequest):
        return await _invoke(resolve, request, body, "cancel")

    @router.post("/admin/queue")
    async def queue(request: Request, body: QueueRequest):
        return await _invoke(resolve, request, body, "queue")

    @router.post("/admin/review")
    async def review(request: Request, body: ReviewRequest):
        return await _invoke(resolve, request, body, "review")

    @router.post("/admin/approve")
    async def approve(request: Request, body: DecisionRequest):
        return await _invoke(resolve, request, body, "approve")

    @router.post("/admin/reject")
    async def reject(request: Request, body: DecisionRequest):
        return await _invoke(resolve, request, body, "reject")

    @router.post("/admin/settle-expiry")
    async def settle(request: Request, body: SettleRequest):
        return await _invoke(resolve, request, body, "settle")

    return router
