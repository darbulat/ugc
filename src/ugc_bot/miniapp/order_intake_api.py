"""Signed service selection with server-owned prices and recipients."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.order_intake_service import OrderIntakeService
from ugc_bot.domain.enums import OrderType
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
    contact_reference: str = Field(min_length=1, max_length=500)
    service_mode: Literal["self_service", "with_manager"]
    accompaniment_ordinals: list[StrictInt] | None = Field(
        default=None, max_length=30
    )
    order_type: OrderType = OrderType.UGC_ONLY
    barter_description: str | None = Field(default=None, max_length=4000)
    targeting: IntakeTargeting | None = None
    funnel_id: UUID | None = None

    @model_validator(mode="after")
    def unique_positions(self) -> Self:
        selected = self.accompaniment_ordinals
        if selected is not None and len(set(selected)) != len(selected):
            raise ValueError("duplicate_accompaniment_ordinals")
        return self


class FunnelStage(SignedMiniAppRequest):
    funnel_id: UUID
    stage: Literal["opened", "brief", "filters", "package"]


class OrderIntakeResponse(BaseModel):
    request_id: UUID
    order_id: UUID
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
        selected = values.pop("accompaniment_ordinals")
        targeting = values.pop("targeting")
        if targeting is not None:
            targeting["platforms"] = tuple(targeting["platforms"])
            values["targeting"] = OrderTargeting(**targeting)
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
        return OrderIntakeResponse(
            **asdict(result),
            total_minor=result.total_minor,
            selection_base_minor=result.selection_base_minor,
        )

    return router
