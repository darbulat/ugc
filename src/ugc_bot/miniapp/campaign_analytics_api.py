"""Signed manual analytics evidence and owner-only reports."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.campaign_analytics import AnalyticsSourceSpec, MetricEvent
from ugc_bot.miniapp.principal import SignedMiniAppRequest

_ERRORS = {
    "analytics_session_invalid": 401,
    "analytics_current_actor_required": 403,
    "analytics_subject_not_found": 404,
    "analytics_source_not_found": 404,
}
_CONFLICTS = (
    "operation_conflict",
    "budget_reference_reused",
    "event_conflict",
    "source_closed",
    "entity_already_recorded",
    "pilot_evidence_reused",
    "subject_changed",
)
_INVALID = (
    "request_invalid",
    "evidence_required",
    "integer_required",
    "subject_required",
    "attribution_window_required",
    "currency_required",
    "currency_mismatch",
    "metric_coverage_required",
    "event_kind_required",
    "event_time_required",
    "distinct_entity_required",
    "paid_amount_required",
    "event_amount_not_applicable",
    "source_required",
    "event_batch_required",
    "event_outside_attribution",
    "metric_not_declared",
    "refund_evidence_required",
    "action_required",
    "future_coverage_unconfirmed",
)
_ERRORS.update({"analytics_" + code: 409 for code in _CONFLICTS})
_ERRORS.update({"analytics_" + code: 422 for code in _INVALID})


class NoStoreAnalyticsRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except Exception as error:
                if isinstance(error, RequestValidationError):
                    code = "analytics_request_invalid"
                elif isinstance(error, HTTPException):
                    code = error.detail
                elif (
                    isinstance(
                        error, (ValueError, LookupError, PermissionError)
                    )
                    and len(error.args) == 1
                ):
                    code = error.args[0]
                else:
                    code = None
                safe = (
                    code
                    if type(code) is str and code in _ERRORS
                    else "analytics_unavailable"
                )
                response = JSONResponse(
                    {"detail": safe}, status_code=_ERRORS.get(safe, 503)
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class SubjectRequest(SignedMiniAppRequest):
    subject_type: Literal["campaign", "order"]
    subject_id: UUID


class PublishRequest(SubjectRequest):
    operation_key: str = Field(min_length=1, max_length=256, strict=True)
    source_name: str = Field(min_length=1, max_length=128, strict=True)
    account_label: str = Field(min_length=1, max_length=128, strict=True)
    attribution_from: datetime
    attribution_until: datetime
    marketing_spend_minor: int = Field(ge=0, strict=True)
    currency: str = Field(min_length=3, max_length=3, strict=True)
    metrics: list[Literal["views", "clicks", "leads", "sales"]] = Field(
        min_length=1, max_length=4
    )
    proof_reference: str = Field(min_length=1, max_length=2048, strict=True)
    budget_reference: str = Field(min_length=1, max_length=2048, strict=True)
    reason: str = Field(min_length=1, max_length=2048, strict=True)


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_event_id: str = Field(min_length=1, max_length=256, strict=True)
    kind: Literal["view", "click", "lead", "sale", "refund"]
    occurred_at: datetime
    entity_id: str = Field(min_length=1, max_length=256, strict=True)
    quantity: int = Field(default=1, ge=1, le=10**9, strict=True)
    amount_minor: int = Field(default=0, ge=0, strict=True)


class SourceRequest(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256, strict=True)
    source_id: UUID


class ImportRequest(SourceRequest):
    events: list[EventRequest] = Field(min_length=1, max_length=1000)


class CloseRequest(SourceRequest):
    action: Literal["finalize", "void"]
    proof_reference: str = Field(min_length=1, max_length=2048, strict=True)
    reason: str = Field(min_length=1, max_length=2048, strict=True)


class PilotRequest(SubjectRequest):
    operation_key: str = Field(min_length=1, max_length=256, strict=True)
    payment_reference: str = Field(min_length=1, max_length=256, strict=True)
    paid_minor: int = Field(ge=1, strict=True)
    currency: str = Field(min_length=3, max_length=3, strict=True)
    proof_reference: str = Field(min_length=1, max_length=2048, strict=True)


def _arguments(actor, body, action):
    args = [actor]
    if action == "report":
        args.extend((body.subject_type, body.subject_id))
    elif action == "publish":
        values = body.model_dump(
            exclude={"init_data", "platform", "operation_key"}
        )
        values["metrics"] = tuple(values["metrics"])
        args.extend((body.operation_key, AnalyticsSourceSpec(**values)))
    elif action == "import_events":
        args.extend(
            (
                body.operation_key,
                body.source_id,
                tuple(
                    MetricEvent(**event.model_dump()) for event in body.events
                ),
            )
        )
    elif action == "close_source":
        args.extend(
            (
                body.operation_key,
                body.source_id,
                body.action,
                body.proof_reference,
                body.reason,
            )
        )
    else:
        args.extend(
            (
                body.operation_key,
                body.subject_type,
                body.subject_id,
                body.payment_reference,
                body.paid_minor,
                body.currency,
                body.proof_reference,
            )
        )
    return args


async def _invoke(resolve, request, body, action):
    if request.query_params:
        raise HTTPException(422, "analytics_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if (
        not isinstance(principal, AuthenticatedMessengerPrincipal)
        or principal.platform != body.platform
    ):
        raise HTTPException(401, "analytics_session_invalid")
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("campaign_analytics_service")
    transaction = getattr(
        dispatcher.get("transaction_manager"), "transaction", None
    )
    if service is None or not callable(transaction):
        raise HTTPException(503, "analytics_unavailable")
    args = _arguments(principal.user_id, body, action)
    async with transaction() as session:
        if session is None:
            raise HTTPException(503, "analytics_unavailable")
        result = await getattr(service, action)(
            *args, principal=principal, session=session
        )
        return JSONResponse(result)


def create_campaign_analytics_router(resolve):
    router = APIRouter(prefix="/analytics", route_class=NoStoreAnalyticsRoute)

    @router.post("/owned/report")
    async def report(request: Request, body: SubjectRequest):
        return await _invoke(resolve, request, body, "report")

    @router.post("/admin/sources/publish")
    async def publish(request: Request, body: PublishRequest):
        return await _invoke(resolve, request, body, "publish")

    @router.post("/admin/events/import")
    async def import_events(request: Request, body: ImportRequest):
        return await _invoke(resolve, request, body, "import_events")

    @router.post("/admin/sources/close")
    async def close(request: Request, body: CloseRequest):
        return await _invoke(resolve, request, body, "close_source")

    @router.post("/admin/paid-pilots/record")
    async def paid_pilot(request: Request, body: PilotRequest):
        return await _invoke(resolve, request, body, "record_paid_pilot")

    return router
