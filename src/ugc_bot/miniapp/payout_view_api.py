"""Strict payout snapshot routes; no command or recovery mutation."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BeforeValidator, Field

from ugc_bot.application.payout_view_ports import Page, PayoutReadNotFound
from ugc_bot.miniapp.payout_api import NoStorePayoutRoute, reply
from ugc_bot.miniapp.payout_read_principal import resolve_payout_read_principal
from ugc_bot.miniapp.payout_wire import parse_minor
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class ReadPage(SignedMiniAppRequest):
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class ReservePreview(SignedMiniAppRequest):
    requisites_id: UUID
    amount_minor: Annotated[
        int, BeforeValidator(lambda v: parse_minor(v, observed=False))
    ]
    currency: Literal["RUB"] = "RUB"


class PayoutViewApi:
    async def _call(self, request, body, method, *args, **kwargs):
        if request.query_params:
            raise HTTPException(422, "payout_read_request_invalid")
        principal = await resolve_payout_read_principal(
            request, body.init_data, platform=body.platform
        )
        service = request.app.state.dispatcher.get("payout_view_service")
        if service is None:
            raise HTTPException(503, "payout_read_unavailable")
        try:
            return reply(
                await getattr(service, method)(principal, *args, **kwargs)
            )
        except PermissionError:
            raise HTTPException(403, "payout_read_forbidden") from None
        except PayoutReadNotFound:
            raise HTTPException(404, "payout_read_not_found") from None
        except ValueError as error:
            if str(error) in ("payout_cursor_invalid", "payout_amount_invalid"):
                raise HTTPException(
                    422, "payout_read_request_invalid"
                ) from None
            raise HTTPException(503, "payout_read_unavailable") from None

    async def context(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "context", page=Page(body.limit, body.cursor)
        )

    async def preview(self, request: Request, body: ReservePreview):
        return await self._call(
            request,
            body,
            "reserve_preview",
            body.requisites_id,
            body.amount_minor,
            currency=body.currency,
        )

    async def own(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "own_page", page=Page(body.limit, body.cursor)
        )

    async def masked(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "masked_page", page=Page(body.limit, body.cursor)
        )

    async def queue(self, request: Request, body: ReadPage):
        return await self._call(
            request, body, "queue_page", page=Page(body.limit, body.cursor)
        )

    async def requirements(self, request: Request, body: ReadPage):
        return await self._call(
            request,
            body,
            "requirements_page",
            page=Page(body.limit, body.cursor),
        )

    async def detail(
        self, request: Request, request_id: UUID, body: SignedMiniAppRequest
    ):
        return await self._call(request, body, "detail", request_id)

    async def history(
        self,
        request: Request,
        request_id: UUID,
        kind: Literal["events", "intents", "outcomes", "settlements"],
        body: ReadPage,
    ):
        return await self._call(
            request,
            body,
            "history_page",
            request_id,
            kind,
            page=Page(body.limit, body.cursor),
        )


def create_payout_view_router():
    router = APIRouter(prefix="/payouts/read", route_class=NoStorePayoutRoute)
    api = PayoutViewApi()
    for path, handler in (
        ("/context", api.context),
        ("/reserve-preview", api.preview),
        ("/own", api.own),
        ("/masked", api.masked),
        ("/admin/queue", api.queue),
        ("/admin/requirements", api.requirements),
        ("/{request_id}/detail", api.detail),
        ("/admin/{request_id}/history/{kind}", api.history),
    ):
        router.add_api_route(path, handler, methods=["POST"])
    return router
