"""Root-mounted signed own draft and aggregate preview endpoints only."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field

from ugc_bot.application.services.campaign_review_service import (
    require_publisher,
)
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.miniapp.campaign_capabilities import submission_available
from ugc_bot.miniapp.campaign_principal import (
    CampaignPrincipalResolver,
    campaign_actor,
    verify_campaign_principal,
)
from ugc_bot.miniapp.principal import PrincipalResolver, SignedMiniAppRequest

UNAVAILABLE = "campaign_drafts_unavailable"
PUBLIC_ERRORS = {
    "campaign_current_publisher_required": 403,
    "campaign_current_policy_required": 403,
    "campaign_principal_changed": 403,
    "existing_campaign_account_required": 404,
    "campaign_actor_not_found": 404,
    "campaign_draft_not_found": 404,
    "campaign_terms_changed": 409,
    "campaign_version_conflict": 409,
    "campaign_operation_conflict": 409,
    "campaign_preview_changed": 409,
    "campaign_inviter_changed": 409,
    "campaign_invalid_page": 422,
    "campaign_content_limits_required": 422,
    "campaign_content_limit_exceeded": 422,
    "campaign_foundation_unavailable": 503,
    "campaign_audience_integrity_unavailable": 503,
    UNAVAILABLE: 503,
    "campaign_request_invalid": 422,
    "campaign_not_editable": 409,
}


class NoStoreCampaignRoute(APIRoute):
    """Never echo rejected drafts, signed input or unexpected exception text."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "campaign_request_invalid"}, status_code=422
                )
            except HTTPException as error:
                code = error.detail
                if (
                    not isinstance(code, str)
                    or PUBLIC_ERRORS.get(code) != error.status_code
                ):
                    code = (
                        "campaign_session_invalid"
                        if error.status_code == 401
                        else UNAVAILABLE
                    )
                response = JSONResponse(
                    {"detail": code},
                    status_code=401
                    if error.status_code == 401
                    else PUBLIC_ERRORS.get(code, 503),
                )
            except Exception:
                response = JSONResponse(
                    {"detail": UNAVAILABLE}, status_code=503
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class DraftSave(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=0, strict=True)
    campaign_id: UUID | None = None
    policy_version: int = Field(ge=1, strict=True)
    terms_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: dict[str, Any]
    segment: dict[str, Any]


class DraftDetail(SignedMiniAppRequest):
    campaign_id: UUID


class DraftPreview(DraftDetail):
    revision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftList(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)


class DraftOperationStatus(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256, strict=True)


def _submission_status(result, available):
    result = dict(result)
    if "campaign_id" in result and "revision_digest" in result:
        result["submission_state"] = (
            "available"
            if available and result.get("state", "draft") == "draft"
            else "unavailable"
        )
    if "current" in result:
        result["current"] = _submission_status(result["current"], available)
    if "drafts" in result:
        result["drafts"] = [
            _submission_status(row, available) for row in result["drafts"]
        ]
    return result


async def _submission_available(dispatcher, service, actor, session):
    if not await submission_available(dispatcher, session=session):
        return False
    try:
        await require_publisher(
            service.foundation, actor, lock=False, session=session
        )
    except PermissionError:
        return False
    return True


async def _invoke(resolve, request, body, action):
    if request.query_params:
        raise HTTPException(422, "campaign_request_invalid")
    identity = await resolve(request, body.init_data, platform=body.platform)
    actor = campaign_actor(identity, platform=body.platform)
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("campaign_review_service")
    audience = dispatcher.get("campaign_audience_service")
    transactions = dispatcher.get("transaction_manager")
    if (
        transactions is None
        or service is None
        or (action == "preview" and audience is None)
    ):
        raise HTTPException(503, UNAVAILABLE)
    try:
        async with transactions.transaction() as session:
            if action == "save":
                payload = body.model_dump(
                    exclude={"init_data", "platform"}, mode="json"
                )
                try:
                    command = SaveCampaignDraft.parse(actor, payload)
                except (ValueError, TypeError):
                    raise HTTPException(
                        422, "campaign_request_invalid"
                    ) from None
                result = await service.save_draft(command, session=session)
            elif action == "detail":
                result = await service.detail(
                    actor, body.campaign_id, session=session
                )
            elif action == "list":
                result = await service.list_drafts(
                    actor, body.page, session=session
                )
            elif action == "operation_status":
                result = await service.operation_status(
                    actor, body.operation_key, session=session
                )
            else:
                result = await audience.preview(
                    actor,
                    body.campaign_id,
                    body.revision_digest,
                    session=session,
                )
            await verify_campaign_principal(
                identity, getattr(service, "foundation", None), session=session
            )
            available = await _submission_available(
                dispatcher, service, actor, session
            )
            return _submission_status(result, available)
    except (PermissionError, LookupError, ValueError) as exc:
        code = str(exc)
        raise HTTPException(
            PUBLIC_ERRORS.get(code, 503),
            code if code in PUBLIC_ERRORS else UNAVAILABLE,
        ) from None


def create_campaign_review_router(
    resolve: PrincipalResolver | CampaignPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/campaigns/owned", route_class=NoStoreCampaignRoute
    )

    @router.post("/draft")
    async def save(request: Request, body: DraftSave):
        return await _invoke(resolve, request, body, "save")

    @router.post("/detail")
    async def detail(request: Request, body: DraftDetail):
        return await _invoke(resolve, request, body, "detail")

    @router.post("/list")
    async def list_drafts(request: Request, body: DraftList):
        return await _invoke(resolve, request, body, "list")

    @router.post("/preview")
    async def preview(request: Request, body: DraftPreview):
        return await _invoke(resolve, request, body, "preview")

    @router.post("/operations/status")
    async def operation_status(request: Request, body: DraftOperationStatus):
        return await _invoke(resolve, request, body, "operation_status")

    return router
