"""Only signed own-client invoice commands; paid outcomes are server-only."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.domain.checkout import CheckoutActor
from ugc_bot.infrastructure.messenger.telegram.invoice_links import (
    TelegramInvoiceLinks,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class InvoiceRequest(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)


class InvoiceRetry(InvoiceRequest):
    previous_attempt_id: UUID


class AuthorizationReview(InvoiceRequest):
    expected_version: int = Field(ge=1, strict=True)
    decision: Literal["confirmed_not_charged"]
    reason: str = Field(min_length=16, max_length=2000)
    evidence_reference: str = Field(min_length=8, max_length=2000)


def _service(request, *, gateway=False):
    if request.query_params:
        raise HTTPException(
            status_code=422, detail="Unexpected query parameters"
        )
    value = request.app.state.dispatcher.get("checkout_service")
    if not isinstance(value, CheckoutService):
        raise HTTPException(status_code=503, detail="checkout_unavailable")
    if gateway:
        bot = getattr(request.app.state, "bot", None)
        if bot is None:
            raise HTTPException(status_code=503, detail="checkout_unavailable")
        config = request.app.state.config
        value = replace(
            value,
            gateway=TelegramInvoiceLinks(
                bot,
                config.bot.telegram_provider_token,
                config.market.receipt_service_description,
            ),
        )
    return value


async def _execute(request, body, action, resolve_actor, *, gateway=False):
    value = _service(request, gateway=gateway)
    actor = await resolve_actor(request, body.init_data, platform=body.platform)
    try:
        return await action(value, actor)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OrderCreationError) as exc:
        code = str(exc)
        status = (
            503
            if code in {"financial_disabled", "payment_provider_not_configured"}
            else 409
            if code
            in {
                "idempotency_payload_conflict",
                "checkout_attempt_changed",
                "payment_authorization_pending",
                "authorization_version_conflict",
                "paid_receipt_pending",
            }
            else 400
        )
        raise HTTPException(status_code=status, detail=code) from exc


def create_checkout_router(
    resolve_actor: Callable[..., Awaitable[CheckoutActor]],
) -> APIRouter:
    router = APIRouter(prefix="/financial")

    async def execute(request, body, action, *, gateway=False):
        return await _execute(
            request, body, action, resolve_actor, gateway=gateway
        )

    @router.post("/orders/{order_id}/invoice")
    async def invoice(order_id: UUID, request: Request, body: InvoiceRequest):
        return await execute(
            request,
            body,
            lambda value, actor: value.request_invoice(
                order_id, actor, body.operation_key
            ),
            gateway=True,
        )

    @router.post("/orders/{order_id}/invoice/retry")
    async def retry(order_id: UUID, request: Request, body: InvoiceRetry):
        return await execute(
            request,
            body,
            lambda value, actor: value.retry_link(
                order_id, actor, body.operation_key, body.previous_attempt_id
            ),
            gateway=True,
        )

    @router.post("/orders/{order_id}/checkout-status")
    async def status(
        order_id: UUID, request: Request, body: SignedMiniAppRequest
    ):
        return await execute(
            request, body, lambda value, actor: value.status(order_id, actor)
        )

    @router.post("/checkout/authorizations/{authorization_id}/review")
    async def review(
        authorization_id: UUID, request: Request, body: AuthorizationReview
    ):
        async def action(value, actor):
            return await value.review_authorization(
                authorization_id,
                actor,
                body.operation_key,
                body.expected_version,
                body.reason,
                body.evidence_reference,
            )

        return await execute(request, body, action)

    @router.post("/checkout/orders/{order_id}/review-context")
    async def review_context(
        order_id: UUID, request: Request, body: SignedMiniAppRequest
    ):
        return await execute(
            request,
            body,
            lambda value, actor: value.review_context(order_id, actor),
        )

    return router
