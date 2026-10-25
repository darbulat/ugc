"""Signed manual subscriptions and their real payment evidence."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    StrictBool,
    StrictInt,
)

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.correction_wire import (
    correction_to_wire,
    parse_observed_minor,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class SubscriptionRoute(_NativeCallerRoute):
    prefix = "subscription"
    codes = SHARED_CODES | {
        "subscription_active_account_required": 403,
        "subscription_current_admin_required": 403,
        "subscription_active_manager_required": 403,
        "subscription_operation_rejected": 409,
        "subscription_unexpected_query": 422,
        "subscription_unavailable": 503,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class Operation(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=4000)


class Tariff(Operation):
    version: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=1000)
    price_minor: Annotated[int, BeforeValidator(parse_observed_minor)] = Field(
        gt=0
    )
    duration_days: StrictInt = Field(gt=0, le=365)
    campaign_limit: StrictInt = Field(gt=0, le=1000000)
    recipient_limit: StrictInt = Field(gt=0, le=10000000)
    terms_reference: str = Field(min_length=1, max_length=1000)


class Evidence(Operation):
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Payment(Evidence):
    member_id: UUID
    tariff_version: str = Field(min_length=1, max_length=1000)
    amount_minor: Annotated[int, BeforeValidator(parse_observed_minor)] = Field(
        gt=0
    )
    currency: Literal["RUB"]
    paid_at: AwareDatetime
    payment_reference: str = Field(min_length=1, max_length=1000)
    pilot: StrictBool


async def _invoke(resolve, request, body, action=None):
    if request.query_params:
        raise HTTPException(422, "subscription_unexpected_query")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    service = request.app.state.dispatcher.get("subscription_service")
    if service is None:
        raise HTTPException(503, "subscription_unavailable")
    try:
        if action is None:
            return correction_to_wire(
                await service.view(principal.user_id, principal=principal)
            )
        payload = body.model_dump(
            exclude={"init_data", "platform", "operation_key"}, mode="json"
        )
        return correction_to_wire(
            await service.execute(
                principal.user_id,
                action,
                body.operation_key,
                payload,
                principal=principal,
            )
        )
    except PermissionError:
        raise
    except (ValueError, LookupError) as error:
        code = error.args[0] if len(error.args) == 1 else None
        if type(code) is str and code == "financial_principal_changed":
            raise
        raise HTTPException(409, "subscription_operation_rejected") from None


def create_subscription_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(prefix="/subscriptions", route_class=SubscriptionRoute)

    @router.post("/view")
    async def view(request: Request, body: SignedMiniAppRequest):
        return await _invoke(resolve, request, body)

    @router.post("/tariffs")
    async def publish(request: Request, body: Tariff):
        return await _invoke(resolve, request, body, "publish")

    @router.post("/payments")
    async def payment(request: Request, body: Payment):
        return await _invoke(resolve, request, body, "accept_payment")

    @router.post("/cancel")
    async def cancel(request: Request, body: Operation):
        return await _invoke(resolve, request, body, "cancel")

    @router.post("/automation")
    async def automation(request: Request, body: Evidence):
        return await _invoke(resolve, request, body, "enable_automation")

    return router
