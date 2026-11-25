"""Signed service selection with server-owned prices and recipients."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.order_intake_service import OrderIntakeService
from ugc_bot.domain.enums import OrderType
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.domain.order_intake import (
    EligibleOrderPolicies,
    IntakeItem,
    OrderIntakeCommand,
)
from ugc_bot.domain.order_targeting import OrderTargeting
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreIntakeRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class IntakeTargeting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    min_followers: int | None = Field(default=None, ge=0, le=2147483647)
    max_followers: int | None = Field(default=None, ge=0, le=2147483647)
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_age: int | None = Field(default=None, ge=0, le=120)
    gender: str | None = None
    city: str | None = Field(default=None, min_length=1, max_length=200)
    platforms: list[
        Literal["instagram", "tiktok", "youtube", "telegram", "vk"]
    ] = Field(default_factory=list, max_length=5)
    content_usage: str | None = Field(
        default=None, min_length=1, max_length=4000
    )
    brief_link: str | None = Field(default=None, min_length=1, max_length=2048)
    deadlines: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def valid_targeting(self) -> Self:
        values = self.model_dump()
        values["platforms"] = tuple(values["platforms"])
        OrderTargeting(**values)
        return self


class OrderIntakeRequest(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    policy_version: str = Field(min_length=1, max_length=256)
    product_link: str = Field(min_length=1, max_length=2048)
    offer_text: str = Field(min_length=1, max_length=4000)
    honorarium: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    selection_due_at: datetime
    contact_reference: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    service_mode: Literal["self_service", "with_manager"]
    position_count: StrictInt = Field(default=30, ge=10, le=200)
    accompaniment_ordinals: list[StrictInt] | None = Field(
        default=None, max_length=200
    )
    order_type: OrderType = OrderType.UGC_ONLY
    barter_description: str | None = Field(default=None, max_length=4000)
    targeting: IntakeTargeting | None = None
    funnel_id: UUID | None = None
    image_token: UUID | None = None
    consultation_requested: StrictBool = False

    @model_validator(mode="after")
    def unique_positions(self) -> Self:
        selected = self.accompaniment_ordinals
        if selected is not None and len(set(selected)) != len(selected):
            raise ValueError("duplicate_accompaniment_ordinals")
        return self


class IntakeCity(SignedMiniAppRequest):
    city: str = Field(min_length=2, max_length=200)


class FunnelStage(SignedMiniAppRequest):
    funnel_id: UUID
    stage: Literal["opened", "brief", "filters", "package"]


class OrderIntakeResponse(BaseModel):
    request_id: UUID
    order_id: UUID
    public_number: str
    requested_at: datetime
    currency: str
    policy_version: str
    selection_due_at: datetime
    terms_reference: str
    items: tuple[IntakeItem, ...]
    lead_id: UUID | None
    honorarium_payment: Literal["paid_direct"]
    targeting: dict | None = None
    total_minor: int
    selection_base_minor: int
    consultation_minor: int = 0
    project_total_minor: int
    consultation_url: str | None = None
    checkout_url: str | None = None
    combined_checkout: bool = False


async def _context(request, body, resolve):
    if request.query_params:
        raise HTTPException(422, "intake_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    service = cast(
        OrderIntakeService | None,
        request.app.state.dispatcher.get("order_intake_service"),
    )
    if service is None:
        raise HTTPException(503, "financial_disabled")
    return principal, service


async def _resolve_intake_city(request: Request, city: str) -> dict:
    geocoder = request.app.state.dispatcher.get("blogger_registration_service")
    result = (
        await geocoder.resolve_city_identity(city.strip()) if geocoder else None
    )
    if result is None:
        raise HTTPException(404, "intake_city_not_found")
    name, region, country = result
    return {"city": name, "region": region, "country": country}


def create_order_intake_router(
    resolve: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/financial/orders",
        route_class=NoStoreIntakeRoute,
    )

    @router.post("/funnel/stage")
    async def funnel_stage(request: Request, body: FunnelStage):
        principal, service = await _context(request, body, resolve)
        return await service.record_funnel(
            principal.user_id, body.funnel_id, body.stage, principal=principal
        )

    @router.post("/funnel/report")
    async def funnel_report(request: Request, body: SignedMiniAppRequest):
        principal, service = await _context(request, body, resolve)
        return await service.funnel_report(
            principal.user_id, principal=principal
        )

    @router.post("/city")
    async def city(request: Request, body: IntakeCity):
        await _context(request, body, resolve)
        return await _resolve_intake_city(request, body.city)

    @router.post("/policies", response_model_exclude_none=True)
    async def policies(
        request: Request, body: SignedMiniAppRequest
    ) -> EligibleOrderPolicies:
        principal, service = await _context(request, body, resolve)
        return await service.eligible_policies(
            principal.user_id,
            principal=principal,
        )

    @router.post("")
    async def create(
        request: Request, body: OrderIntakeRequest
    ) -> OrderIntakeResponse:
        principal, service = await _context(request, body, resolve)
        values = body.model_dump(exclude={"init_data", "platform"})
        if values.get("contact_reference") is None:
            values["contact_reference"] = (
                f"{principal.platform}:{principal.external_id}"
            )
        selected = values.pop("accompaniment_ordinals")
        targeting = values.pop("targeting")
        if targeting is not None:
            targeting["platforms"] = tuple(targeting["platforms"])
            values["targeting"] = OrderTargeting(**targeting)
        try:
            result = await service.create(
                OrderIntakeCommand(
                    client_id=principal.user_id,
                    accompaniment_ordinals=(
                        frozenset(selected) if selected is not None else None
                    ),
                    **values,
                ),
                principal=principal,
            )
        except PermissionError as error:
            if (
                error.args == ("registration_agreement_required",)
                and request.headers.get("X-UMC-Agreement-Recovery") != "1"
            ):
                # Older Mini Apps interpret 401 as a request to reopen the app.
                raise HTTPException(
                    401, "registration_agreement_required"
                ) from None
            raise
        return OrderIntakeResponse(
            **asdict(result),
            public_number=public_order_number(result.order_id),
            total_minor=result.total_minor,
            selection_base_minor=result.selection_base_minor,
            project_total_minor=result.project_total_minor,
            consultation_url=service.consultation_link(result)
            if result.consultation_token and not result.combined_checkout
            else None,
            checkout_url=service.checkout_link(result)
            if result.checkout_token
            else None,
        )

    return router
