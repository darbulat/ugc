"""Existing-account signed correction evidence; no bank transfer endpoint."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, BeforeValidator, Field

from ugc_bot.application.correction_ports import (
    ApplySelectionRefund,
    MatchSelectionRefund,
    RecordManualRefundObservation,
    RequestSelectionRefund,
    ReviewSelectionRefund,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.financial import MAX_MINOR
from ugc_bot.miniapp.correction_wire import (
    PUBLIC_CORRECTION_CODES,
    correction_to_wire,
    parse_observed_minor,
    public_correction_code,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest

HTTP_CODES = PUBLIC_CORRECTION_CODES | {
    "correction_not_found",
    "correction_request_invalid",
    "financial_session_invalid",
    "existing_financial_account_required",
    "financial_unavailable",
}


class NoStoreCorrectionRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "correction_request_invalid"}, status_code=422
                )
            except HTTPException as error:
                code = error.detail if isinstance(error.detail, str) else None
                raise HTTPException(
                    error.status_code if code in HTTP_CODES else 503,
                    code if code in HTTP_CODES else "correction_unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            except Exception:
                raise HTTPException(
                    503,
                    "correction_unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class ReadPage(SignedMiniAppRequest):
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    cursor: str | None = Field(default=None, min_length=1, max_length=36)


class Preview(SignedMiniAppRequest):
    order_id: UUID
    paid_item_ids: tuple[UUID, ...] = Field(min_length=1, max_length=200)
    existing_case_id: UUID | None = None


class Operation(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)


class Command(Operation):
    reason: str = Field(min_length=1, max_length=4000)


class RefundRequest(Command, Preview):
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Evidence(Command):
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Review(Evidence):
    case_id: UUID
    expected_version: int = Field(ge=1, le=MAX_MINOR, strict=True)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approve", "reject"]


class Observation(Evidence):
    case_id: UUID | None = None
    known_order_id: UUID | None = None
    known_capture_intent_id: UUID | None = None
    original_payment_reference: str = Field(default="", max_length=4000)
    bank_account_label: str = Field(default="", max_length=4000)
    bank_reference: str = Field(min_length=1, max_length=4000)
    amount_minor: Annotated[
        int | None, BeforeValidator(parse_observed_minor)
    ] = None
    currency: str | None = Field(default=None, max_length=64)
    occurred_at: AwareDatetime | None = None
    reported_component: Literal[
        "selection", "accompaniment", "management", "replacement", "unknown"
    ]
    expected_version: int | None = Field(
        default=None, ge=1, le=MAX_MINOR, strict=True
    )


class Match(Evidence):
    case_id: UUID
    intent_id: UUID
    observation_id: UUID
    expected_version: int = Field(ge=1, le=MAX_MINOR, strict=True)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Apply(Match):
    match_id: UUID


def failure(error):
    code = public_correction_code(error)
    forbidden = {
        "correction_active_actor_required",
        "correction_active_admin_required",
        "correction_own_client_required",
        "financial_principal_changed",
    }
    return HTTPException(
        503
        if code == "correction_unavailable"
        else 403
        if code in forbidden
        else 409,
        code,
    )


class CorrectionApi:
    def __init__(self, resolve):
        self.resolve = resolve

    async def _context(self, request, body, *, read):
        if request.query_params:
            raise HTTPException(422, "correction_request_invalid")
        actor = await self.resolve(
            request, body.init_data, platform=body.platform
        )
        if (
            not isinstance(actor, AuthenticatedMessengerPrincipal)
            or actor.platform != body.platform
        ):
            raise HTTPException(401, "financial_session_invalid")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get(
            "correction_view_service" if read else "correction_service"
        )
        transactions = dispatcher.get("transaction_manager")
        if service is None or transactions is None:
            raise HTTPException(503, "correction_unavailable")
        return actor, service, transactions

    async def _call(self, request, body, method, *, read=True, **kwargs):
        actor, service, transactions = await self._context(
            request, body, read=read
        )
        try:
            async with transactions.transaction() as session:
                value = await getattr(service, method)(
                    actor.user_id,
                    session=session,
                    principal=actor,
                    **kwargs,
                )
                return JSONResponse(jsonable_encoder(correction_to_wire(value)))
        except ValueError as error:
            raise failure(error) from None
        except LookupError as error:
            if str(error) != "correction_not_found":
                raise
            raise HTTPException(404, "correction_not_found") from None

    async def _execute(self, request, body, constructor):
        actor, service, transactions = await self._context(
            request, body, read=False
        )
        if (
            not request.app.state.config.financial.core_enabled
            and constructor is not RecordManualRefundObservation
        ):
            raise HTTPException(503, "financial_corrections_disabled")
        try:
            command = constructor(
                actor_id=actor.user_id,
                **body.model_dump(exclude={"init_data", "platform"}),
            )
            async with transactions.transaction() as session:
                value = await service.execute(
                    command, session=session, principal=actor
                )
                return JSONResponse(jsonable_encoder(correction_to_wire(value)))
        except ValueError as error:
            raise failure(error) from None

    async def context(self, request: Request, body: SignedMiniAppRequest):
        return await self._call(request, body, "context")

    async def cases(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "cases", limit=body.limit, cursor=body.cursor
        )

    async def queue(self, request: Request, body: ReadPage):
        return await self._call(
            request,
            body,
            "cases",
            admin=True,
            limit=body.limit,
            cursor=body.cursor,
        )

    async def orders(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "orders", limit=body.limit, cursor=body.cursor
        )

    async def preview(self, request: Request, body: Preview):
        return await self._call(
            request,
            body,
            "preview",
            **body.model_dump(exclude={"init_data", "platform"}),
        )

    async def detail(
        self, request: Request, case_id: UUID, body: SignedMiniAppRequest
    ):
        return await self._call(request, body, "detail", case_id=case_id)

    async def operation(self, request: Request, body: Operation):
        return await self._call(
            request,
            body,
            "operation_for_actor",
            read=False,
            operation_key=body.operation_key,
        )

    async def refund_request(self, request: Request, body: RefundRequest):
        return await self._execute(request, body, RequestSelectionRefund)

    async def review(self, request: Request, body: Review):
        return await self._execute(request, body, ReviewSelectionRefund)

    async def observe(self, request: Request, body: Observation):
        return await self._execute(request, body, RecordManualRefundObservation)

    async def match(self, request: Request, body: Match):
        return await self._execute(request, body, MatchSelectionRefund)

    async def apply(self, request: Request, body: Apply):
        return await self._execute(request, body, ApplySelectionRefund)


def create_correction_router(resolve_principal: FinancialPrincipalResolver):
    router = APIRouter(
        prefix="/financial/corrections", route_class=NoStoreCorrectionRoute
    )
    api = CorrectionApi(resolve_principal)
    for path, handler in (
        ("/context", api.context),
        ("/list", api.cases),
        ("/admin/queue", api.queue),
        ("/orders", api.orders),
        ("/preview", api.preview),
        ("/{case_id}/detail", api.detail),
        ("/request", api.refund_request),
        ("/admin/review", api.review),
        ("/admin/observation", api.observe),
        ("/admin/match", api.match),
        ("/admin/apply", api.apply),
        ("/operations/status", api.operation),
    ):
        router.add_api_route(path, handler, methods=["POST"])
    return router
