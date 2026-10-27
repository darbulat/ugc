"""Strict signed campaign configuration/settings, with no dispatch endpoint."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictInt

from ugc_bot.domain.campaigns import CampaignCommand, CampaignConflict
from ugc_bot.miniapp.campaign_capabilities import (
    delivery_state,
    submission_available,
)
from ugc_bot.miniapp.campaign_principal import (
    CampaignPrincipalResolver,
    campaign_actor,
    verify_campaign_principal,
)
from ugc_bot.miniapp.principal import PrincipalResolver, SignedMiniAppRequest


class CampaignOperation(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=0, strict=True)


class PolicyPublish(CampaignOperation):
    terms_version: str = Field(min_length=1, max_length=1000)
    default_locale: str
    terms: dict[str, str]
    limits: dict[str, StrictInt]
    reason: str = Field(min_length=1, max_length=1000)


class PolicySuspend(CampaignOperation):
    reason: str = Field(min_length=1, max_length=1000)


class PublisherChange(PolicySuspend):
    owner_id: UUID


class ConsentAllow(CampaignOperation):
    policy_version: int = Field(ge=1, strict=True)
    terms_hash: str = Field(min_length=64, max_length=64)
    consent_context: str = Field(pattern=r"^[0-9a-f]{64}$")


class AccountLookup(SignedMiniAppRequest):
    search: str = Field(default="", max_length=100)
    page: int = Field(default=0, ge=0, le=100000, strict=True)


def _workbench_capabilities(dispatcher, view, *, submission_ready=False):
    review = dispatcher.get("campaign_review_service")
    audience = dispatcher.get("campaign_audience_service")
    readable = all(
        callable(getattr(review, method, None))
        for method in ("list_drafts", "detail")
    )
    writable = bool(
        (view.get("publisher") or {}).get("active") is True
        and (view.get("policy") or {}).get("enabled") is True
    )
    return {
        "read_own_drafts": readable,
        "read_own_operations": readable
        and callable(getattr(review, "operation_status", None)),
        "save_draft": readable
        and writable
        and callable(getattr(review, "save_draft", None)),
        "preview_audience": readable
        and writable
        and callable(getattr(audience, "preview", None)),
        "submit_campaign": submission_ready
        and writable
        and callable(
            getattr(
                dispatcher.get("campaign_submission_service"), "submit", None
            )
        ),
        "cancel_campaign": submission_ready
        and callable(
            getattr(
                dispatcher.get("campaign_moderation_service"), "cancel", None
            )
        ),
        "read_admin_queue": submission_ready
        and view.get("can_admin") is True
        and callable(
            getattr(
                dispatcher.get("campaign_moderation_service"), "queue", None
            )
        ),
        "review_campaign": submission_ready
        and view.get("can_admin") is True
        and callable(
            getattr(
                dispatcher.get("campaign_moderation_service"), "decide", None
            )
        ),
    }


async def _invoke(resolve, request, body, *, action=None, accounts=False):
    if request.query_params:
        raise HTTPException(422, "Unexpected query parameters")
    identity = await resolve(request, body.init_data, platform=body.platform)
    actor = campaign_actor(identity, platform=body.platform)
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("campaign_service")
    transactions = dispatcher.get("transaction_manager")
    if service is None or transactions is None:
        raise HTTPException(503, "Campaign settings unavailable")
    try:
        async with transactions.transaction() as session:
            if accounts:
                result = await service.accounts(
                    actor, body.search, body.page, session=session
                )
            elif action is None:
                view = await service.view(actor, session=session)
                ready = await submission_available(dispatcher, session=session)
                result = {
                    **view,
                    "delivery_state": delivery_state(
                        getattr(request.app.state, "config", None),
                        dispatcher,
                        submission_ready=ready,
                    ),
                    "capabilities": _workbench_capabilities(
                        dispatcher, view, submission_ready=ready
                    ),
                }
            else:
                payload: dict[str, Any] = body.model_dump(
                    exclude={
                        "init_data",
                        "platform",
                        "operation_key",
                        "expected_version",
                    },
                    mode="json",
                )
                command = CampaignCommand(
                    actor,
                    body.operation_key,
                    action,
                    body.expected_version,
                    payload,
                )
                result = await service.execute(command, session=session)
            await verify_campaign_principal(
                identity, getattr(service, "repository", None), session=session
            )
            return result
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CampaignConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        status = 503 if str(exc) == "campaign_foundation_unavailable" else 422
        raise HTTPException(status, str(exc)) from exc


def create_campaign_router(
    resolve: PrincipalResolver | CampaignPrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/campaigns")

    @router.post("/settings")
    async def settings(request: Request, body: SignedMiniAppRequest):
        return await _invoke(resolve, request, body)

    @router.post("/admin/accounts")
    async def accounts(request: Request, body: AccountLookup):
        return await _invoke(resolve, request, body, accounts=True)

    @router.post("/policy/publish")
    async def publish(request: Request, body: PolicyPublish):
        return await _invoke(resolve, request, body, action="publish")

    @router.post("/policy/suspend")
    async def suspend(request: Request, body: PolicySuspend):
        return await _invoke(resolve, request, body, action="suspend")

    @router.post("/publishers/grant")
    async def grant(request: Request, body: PublisherChange):
        return await _invoke(resolve, request, body, action="grant")

    @router.post("/publishers/revoke")
    async def revoke(request: Request, body: PublisherChange):
        return await _invoke(resolve, request, body, action="revoke")

    @router.post("/consent/allow")
    async def allow(request: Request, body: ConsentAllow):
        return await _invoke(resolve, request, body, action="consent")

    @router.post("/consent/revoke")
    async def unsubscribe(request: Request, body: CampaignOperation):
        return await _invoke(resolve, request, body, action="unsubscribe")

    return router
