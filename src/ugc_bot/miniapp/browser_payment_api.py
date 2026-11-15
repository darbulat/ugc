"""Pay through an order-specific link without a messenger session."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import UUID4, BaseModel, Field

from ugc_bot.application.errors import OrderCreationError

router = APIRouter(prefix="/browser-payment")
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class PaymentLink(BaseModel):
    token: UUID4


class StartPayment(PaymentLink):
    email: str = Field(max_length=254)


async def _status(checkout, token):
    if checkout is None:
        return JSONResponse({"state": "unavailable"}, headers=_HEADERS)
    try:
        view = await checkout.buyer_view(token)
    except LookupError:
        view = {"state": "unavailable"}
    return JSONResponse(view, headers=_HEADERS)


@router.post("/status")
async def browser_payment_status(request: Request, body: PaymentLink):
    checkout = getattr(request.app.state, "browser_checkout", None)
    return await _status(checkout, body.token)


@router.post("/start")
async def browser_payment_start(request: Request, body: StartPayment):
    checkout = getattr(request.app.state, "browser_checkout", None)
    if checkout is not None:
        try:
            await checkout.start(body.token, body.email)
        except LookupError:
            return JSONResponse({"state": "unavailable"}, headers=_HEADERS)
        except OrderCreationError as exc:
            if str(exc) == "browser_receipt_email_required":
                return JSONResponse(
                    {"error": "Укажите корректный email для чека."},
                    status_code=422,
                    headers=_HEADERS,
                )
            if str(exc) not in {
                "telegram_payment_pending",
                "order_not_payable",
                "browser_payment_quote_not_unpaid",
                "browser_payment_paused",
            }:
                return JSONResponse({"state": "unavailable"}, headers=_HEADERS)
    return await _status(checkout, body.token)
