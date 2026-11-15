"""Private contact controls for the owner of a Telegram order."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class NoStoreHandoffRoute(_NativeCallerRoute):
    prefix = "invite_handoff"
    http_pairs = {}
    codes = SHARED_CODES | {
        "invite_handoff_unavailable": 503,
        "invite_order_unavailable": 404,
        "creator_invite_contact_unavailable": 404,
        "invite_client_telegram_required": 422,
    }


class HandoffRequest(SignedMiniAppRequest):
    action: Literal["view", "share", "hide", "open", "ack"] = "view"
    invitation: UUID | None = None


def create_invite_handoff_router(resolve):
    router = APIRouter(
        prefix="/financial/orders", route_class=NoStoreHandoffRoute
    )

    @router.post("/{order_id}/invite-handoff")
    async def handoff(order_id: UUID, request: Request, body: HandoffRequest):
        if body.platform != "telegram":
            raise HTTPException(404, "invite_order_unavailable")
        service = request.app.state.dispatcher.get("creator_invite_service")
        if service is None:
            raise HTTPException(503, "invite_handoff_unavailable")
        principal = await resolve(
            request, body.init_data, platform=body.platform
        )
        try:
            if body.action in ("open", "ack"):
                if body.invitation is None:
                    raise HTTPException(422, "invite_handoff_request_invalid")
                if (
                    await service.reported_contact(principal, body.invitation)
                    != order_id
                ):
                    raise PermissionError("invite_order_unavailable")
                if body.action == "open":
                    return {
                        "contact": await service.reported_contact_text(
                            principal, body.invitation
                        )
                    }
                await service.acknowledge_staff_contact(
                    principal, body.invitation
                )
                return {"acknowledged": True}
            enabled = {"share": True, "hide": False}.get(body.action)
            data = await service.client_sharing(principal, order_id, enabled)
            username = request.app.state.config.bot.bot_username.strip().lstrip(
                "@"
            )
            return data | {
                "open_url": f"https://t.me/{username}?start=ir_{order_id.hex}"
            }
        except PermissionError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    return router
