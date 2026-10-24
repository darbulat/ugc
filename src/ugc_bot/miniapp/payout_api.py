"""Strict signed own/admin payout ingress; never accepts caller money proof."""

from datetime import datetime
from typing import Annotated, Any, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
)

from ugc_bot.application.errors import LegacyPayoutBlockedError
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.payout_contract_ports import (
    PayoutFieldDefinition,
    TermsDocumentInput,
)
from ugc_bot.application.payout_errors import (
    PUBLIC_PAYOUT_CODES,
    public_payout_code,
)
from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    RecordPayoutResult,
    RequestPayout,
    ReviewPayout,
    StorePayoutRequisites,
)
from ugc_bot.domain.financial import MAX_MINOR
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.payout_wire import parse_minor, payout_to_wire
from ugc_bot.miniapp.principal import SignedMiniAppRequest

PUBLIC_PAYOUT_HTTP_CODES = PUBLIC_PAYOUT_CODES | frozenset(
    {
        "payout_request_invalid",
        "payout_unavailable",
        "legacy_payout_blocked",
        "financial_session_invalid",
        "existing_financial_account_required",
        "financial_unavailable",
        "payout_read_session_invalid",
        "payout_read_unavailable",
        "existing_payout_account_required",
        "payout_read_request_invalid",
        "payout_read_forbidden",
        "payout_read_not_found",
        "Invalid Mini App session",
        "Ambiguous Mini App session",
        "Invalid Mini App auth_date",
        "Mini App session expired. Reopen the app.",
    }
)


class NoStorePayoutRoute(APIRoute):
    """Never echo unvalidated private payloads or cache protected errors."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "payout_request_invalid"}, status_code=422
                )
            except HTTPException as error:
                if (
                    not isinstance(error.detail, str)
                    or error.detail not in PUBLIC_PAYOUT_HTTP_CODES
                ):
                    raise HTTPException(
                        503,
                        "payout_unavailable",
                        headers={"Cache-Control": "no-store"},
                    ) from None
                error.headers = {
                    **(error.headers or {}),
                    "Cache-Control": "no-store",
                }
                raise
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail="payout_unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class Operation(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID | None = None
    content_text: str | None = Field(default=None, max_length=1000000)
    source_locale: str | None = Field(default=None, max_length=35)


class FieldDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    labels: dict[str, str]
    help: dict[str, str] = Field(default_factory=dict)
    allowed_values: tuple[str, ...] | None = None


class PublishRequirements(Operation):
    expected_version: int = Field(ge=0, strict=True)
    effective_from: AwareDatetime
    legal_reference: str = Field(min_length=1, max_length=4000)
    terms_reference: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    required_fields: tuple[str, ...]
    enabled: bool = Field(strict=True)
    document: DocumentInput | None = None
    field_definitions: tuple[FieldDefinitionInput, ...] | None = None


class Requisites(Operation):
    requirements_id: UUID
    accepted_terms_reference: str = Field(min_length=1, max_length=4000)
    details: dict[str, str]
    accepted_document_id: UUID | None = None
    accepted_document_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    accepted: bool | None = Field(default=None, strict=True)


class Reserve(Operation):
    requisites_id: UUID
    amount_minor: Annotated[
        int, BeforeValidator(lambda v: parse_minor(v, observed=False))
    ] = Field(ge=1, le=MAX_MINOR, strict=True)
    currency: Literal["RUB"] = "RUB"


class Review(Operation):
    request_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    action: Literal["review", "reject", "start", "escalate"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(default="", max_length=4000)


class BankResult(Operation):
    request_id: UUID
    execution_id: UUID
    fence: UUID
    expected_version: int = Field(ge=1, strict=True)
    status: Literal["paid", "failed", "unknown"]
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bank_account: str = Field(default="", max_length=256)
    bank_reference: str = Field(default="", max_length=256)
    amount_minor: Annotated[
        int | None, BeforeValidator(lambda v: parse_minor(v, observed=True))
    ] = Field(default=None, ge=-MAX_MINOR, le=MAX_MINOR, strict=True)
    currency: str | None = Field(default=None, max_length=20)
    settled_at: AwareDatetime | None = None
    recipient_details: dict[str, str] = Field(default_factory=dict)


class Reveal(Operation):
    reason: str = Field(min_length=1, max_length=4000)


class Queue(SignedMiniAppRequest):
    limit: int = Field(default=100, ge=1, le=100, strict=True)


def reply(value):
    return JSONResponse(
        jsonable_encoder(payout_to_wire(value)),
        headers={"Cache-Control": "no-store"},
    )


def failure(error):
    code = public_payout_code(error)
    return HTTPException(
        503
        if code == "payout_unavailable"
        else 403
        if code
        in (
            "financial_principal_changed",
            "active_admin_required",
            "active_actor_required",
            "payout_own_or_admin_required",
            "payout_own_requisites_required",
        )
        else 409,
        code,
    )


class _PayoutApi:
    def __init__(self, resolve):
        self.resolve = resolve

    async def context(self, request, body):
        if request.query_params:
            raise HTTPException(422, "payout_request_invalid")
        actor = await self.resolve(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(actor, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        service = request.app.state.dispatcher.get("payout_service")
        transactions = request.app.state.dispatcher.get("transaction_manager")
        if service is None or transactions is None:
            raise HTTPException(503, "payout_unavailable")
        return actor, service, transactions

    async def execute(self, request, body, constructor):
        actor, service, transactions = await self.context(request, body)
        gates = request.app.state.config.financial
        if (
            not gates.core_enabled or not gates.payouts_enabled
        ) and constructor is not RecordPayoutResult:
            raise HTTPException(503, "financial_payouts_disabled")
        try:
            values = body.model_dump(exclude={"init_data", "platform"})
            if constructor is PublishPayoutRequirements:
                if values["document"] is not None:
                    values["document"] = TermsDocumentInput(
                        **values["document"]
                    )
                if values["field_definitions"] is not None:
                    values["field_definitions"] = tuple(
                        PayoutFieldDefinition(**v)
                        for v in values["field_definitions"]
                    )
            command = constructor(actor_id=actor.user_id, **values)
            async with transactions.transaction() as db:
                value = await service.execute(
                    command, session=db, principal=actor
                )
            return reply(value)
        except (ValueError, LegacyPayoutBlockedError) as error:
            raise failure(error) from None

    async def read(self, request, body, call, *, not_found=False):
        actor, service, transactions = await self.context(request, body)
        try:
            async with transactions.transaction() as db:
                value = await call(service, actor.user_id, db, actor)
            if not_found and value is None:
                raise HTTPException(404, "payout_not_found")
            return reply(value)
        except ValueError as error:
            raise failure(error) from None

    async def publish(self, request: Request, body: PublishRequirements):
        return await self.execute(request, body, PublishPayoutRequirements)

    async def requisites(self, request: Request, body: Requisites):
        return await self.execute(request, body, StorePayoutRequisites)

    async def reserve(self, request: Request, body: Reserve):
        return await self.execute(request, body, RequestPayout)

    async def review(self, request: Request, body: Review):
        return await self.execute(request, body, ReviewPayout)

    async def result(self, request: Request, body: BankResult):
        return await self.execute(request, body, RecordPayoutResult)

    async def requirements(self, request: Request, body: SignedMiniAppRequest):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.requirements_for_actor(
                a, session=db, principal=p
            ),
        )

    async def admin_requirements(
        self, request: Request, body: SignedMiniAppRequest
    ):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.requirements_for_admin(
                a, session=db, principal=p
            ),
        )

    async def history(
        self, request: Request, request_id: UUID, body: SignedMiniAppRequest
    ):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.history_for_admin(
                request_id, a, session=db, principal=p
            ),
            not_found=True,
        )

    async def own_list(self, request: Request, body: SignedMiniAppRequest):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.list_for_actor(a, session=db, principal=p),
        )

    async def _queue(self, service, actor, db, limit, principal):
        values = await service.list_for_actor(
            actor, admin=True, session=db, principal=principal
        )
        now = service.clock.now()
        return [
            v | {"overdue": now >= datetime.fromisoformat(v["deadline_at"])}
            for v in values
            if v["state"] not in ("paid", "rejected") or v["block_reason"]
        ][:limit]

    async def queue(self, request: Request, body: Queue):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: self._queue(s, a, db, body.limit, p),
        )

    async def reveal(self, request: Request, request_id: UUID, body: Reveal):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.reveal_for_admin(
                request_id,
                a,
                operation_key=body.operation_key,
                reason=body.reason,
                session=db,
                principal=p,
            ),
        )

    async def operation_status(self, request: Request, body: Operation):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.operation_for_actor(
                a, body.operation_key, session=db, principal=p
            ),
        )

    async def requisites_list(
        self, request: Request, body: SignedMiniAppRequest
    ):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.requisites_for_actor(
                a, session=db, principal=p
            ),
        )

    async def status(
        self, request: Request, request_id: UUID, body: SignedMiniAppRequest
    ):
        return await self.read(
            request,
            body,
            lambda s, a, db, p: s.get_for_actor(
                request_id, a, session=db, principal=p
            ),
            not_found=True,
        )


def create_payout_router(resolve_principal: FinancialPrincipalResolver):
    router = APIRouter(prefix="/payouts", route_class=NoStorePayoutRoute)
    api = _PayoutApi(resolve_principal)
    routes: dict[str, Callable[..., Any]] = {
        "/admin/requirements/publish": api.publish,
        "/requisites": api.requisites,
        "/request": api.reserve,
        "/admin/command": api.review,
        "/admin/result": api.result,
        "/requirements": api.requirements,
        "/list": api.own_list,
        "/admin/queue": api.queue,
        "/admin/requirements": api.admin_requirements,
        "/admin/{request_id}/history": api.history,
        "/admin/{request_id}/requisites": api.reveal,
        "/operations/status": api.operation_status,
        "/requisites/list": api.requisites_list,
        "/{request_id}/status": api.status,
    }
    for path, handler in routes.items():
        router.add_api_route(path, handler, methods=["POST"])
    return router
