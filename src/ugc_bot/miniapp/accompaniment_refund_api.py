"""Reviewed actual accompaniment refunds, with no bank-transfer commands."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BeforeValidator, Field

from ugc_bot.application.accompaniment_refund_ports import (
    ApplyAccompanimentRefund,
    ObserveAccompanimentRefund,
    ReviewAccompanimentManagement,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.correction_api import NoStoreCorrectionRoute
from ugc_bot.miniapp.correction_wire import (
    correction_to_wire,
    parse_observed_minor,
    public_correction_code,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class Command(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    paid_item_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Observe(Command):
    original_payment_reference: str = Field(min_length=1, max_length=4000)
    amount_minor: Annotated[int, BeforeValidator(parse_observed_minor)]
    currency: str = Field(min_length=1, max_length=64)
    bank_account_label: str = Field(min_length=1, max_length=256)
    bank_reference: str = Field(min_length=1, max_length=4000)
    occurred_at: AwareDatetime


class Apply(Command):
    observation_id: UUID
    expected_work_version: int = Field(ge=0, strict=True)
    reviewed_customer_target_minor: Annotated[
        int | None, BeforeValidator(parse_observed_minor)
    ] = None
    reviewed_manager_target_minor: Annotated[
        int | None, BeforeValidator(parse_observed_minor)
    ] = None


class Management(Command):
    application_id: UUID
    expected_work_version: int = Field(ge=1, strict=True)
    decision: Literal["continue", "cancel"]


async def _invoke(resolve, request, body, constructor, method):
    if request.query_params:
        raise HTTPException(422, "correction_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    if not request.app.state.config.financial.core_enabled:
        raise HTTPException(503, "financial_corrections_disabled")
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("accompaniment_refund_service")
    tm = dispatcher.get("transaction_manager")
    if service is None or tm is None:
        raise HTTPException(503, "correction_unavailable")
    try:
        command = constructor(
            actor_id=principal.user_id,
            **body.model_dump(exclude={"init_data", "platform"}),
        )
        async with tm.transaction() as session:
            result = await getattr(service, method)(
                command, session=session, principal=principal
            )
            return jsonable_encoder(correction_to_wire(result))
    except PermissionError:
        raise HTTPException(403, "correction_active_admin_required") from None
    except ValueError as error:
        code = public_correction_code(error)
        raise HTTPException(
            503 if code == "correction_unavailable" else 409, code
        ) from None


def create_accompaniment_refund_router(resolve):
    router = APIRouter(
        prefix="/financial/corrections/admin/accompaniment",
        route_class=NoStoreCorrectionRoute,
    )

    @router.post("/observe")
    async def observe(request: Request, body: Observe):
        return await _invoke(
            resolve, request, body, ObserveAccompanimentRefund, "observe"
        )

    @router.post("/apply")
    async def apply(request: Request, body: Apply):
        return await _invoke(
            resolve, request, body, ApplyAccompanimentRefund, "apply"
        )

    @router.post("/management")
    async def management(request: Request, body: Management):
        return await _invoke(
            resolve,
            request,
            body,
            ReviewAccompanimentManagement,
            "review_management",
        )

    return router
