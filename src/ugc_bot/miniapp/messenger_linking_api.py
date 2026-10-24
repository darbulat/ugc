"""Existing-only signed MAX consent; no public Telegram proof endpoint."""

from time import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field

from ugc_bot.application.services.messenger_linking_service import (
    MessengerLinkingService,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.messenger_linking import MaxLinkActor
from ugc_bot.miniapp.auth import validate_init_data_for_platform
from ugc_bot.miniapp.principal import (
    SignedMiniAppRequest,
    require_messenger_link_init_data,
)


class NoStoreLinkRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "invalid_link_request"}, status_code=422
                )
            except HTTPException as exc:
                exc.headers = {
                    **(exc.headers or {}),
                    "Cache-Control": "no-store",
                }
                raise
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail="messenger_linking_unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


def view_payload(view):
    receipt = view.receipt
    safe_receipt = (
        None
        if receipt is None
        else {
            "command_id": receipt.command_id,
            "kind": receipt.kind,
            "challenge_id": receipt.challenge_id,
            "state": receipt.state,
            "version": receipt.version,
            "claim_id": receipt.claim_id,
        }
    )
    return jsonable_encoder(
        {
            "state": view.state,
            "challenge_id": view.challenge_id,
            "version": view.version,
            "claim_id": view.claim_id,
            "expires_at": view.expires_at,
            "telegram_identity": view.telegram_identity,
            "enabled": view.enabled,
            "can_create": view.can_create,
            "can_confirm": view.can_confirm,
            "can_revoke": view.can_revoke,
            "launch_url": view.launch_url,
            "receipt": safe_receipt,
        }
    )


class ChallengeCommand(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)


class LinkStatus(SignedMiniAppRequest):
    challenge_id: UUID | None = None


class RevokeCommand(ChallengeCommand):
    challenge_id: UUID
    expected_version: int = Field(ge=1, strict=True)


class ConfirmCommand(RevokeCommand):
    claim_id: UUID


async def resolve_existing_max_actor(
    request: Request, init_data: str, *, platform: str
) -> MaxLinkActor:
    if platform != "max":
        raise HTTPException(
            status_code=403, detail="original_max_owner_required"
        )
    require_messenger_link_init_data(init_data, now=time())
    config = request.app.state.config
    max_config = config.max_bot
    if max_config is None or not max_config.token:
        raise HTTPException(
            status_code=503, detail="messenger_linking_unavailable"
        )
    try:
        external_id = validate_init_data_for_platform(
            init_data,
            platform="max",
            telegram_bot_token=config.bot.bot_token,
            max_bot_token=max_config.token,
        )
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Invalid MAX session"
        ) from None
    roles = request.app.state.dispatcher.get("user_role_service")
    if roles is None:
        raise HTTPException(
            status_code=503, detail="messenger_linking_unavailable"
        )
    user = await roles.get_user(external_id, MessengerType.MAX)
    if user is None or user.max_id != external_id:
        raise HTTPException(
            status_code=404, detail="existing_max_account_required"
        )
    return MaxLinkActor(user.user_id, external_id)


async def _execute(request, body, action):
    if request.query_params:
        raise HTTPException(
            status_code=422, detail="Unexpected query parameters"
        )
    service = request.app.state.dispatcher.get("messenger_linking_service")
    if not isinstance(service, MessengerLinkingService):
        raise HTTPException(
            status_code=503, detail="messenger_linking_unavailable"
        )
    actor = await resolve_existing_max_actor(
        request, body.init_data, platform=body.platform
    )
    try:
        return view_payload(await action(service, actor))
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="messenger_identity_changed"
        ) from None
    except LookupError:
        raise HTTPException(
            status_code=404, detail="messenger_link_not_found"
        ) from None
    except ValueError as exc:
        # Expected repository errors contain stable codes only.
        code = str(exc)
        allowed = {
            "idempotency_payload_conflict",
            "invalid_operation_key",
            "link_version_conflict",
            "link_not_confirmable",
            "link_not_revocable",
        }
        raise HTTPException(
            status_code=409 if code in allowed else 503,
            detail=code if code in allowed else "messenger_linking_unavailable",
        ) from None


def create_messenger_linking_router() -> APIRouter:
    router = APIRouter(
        prefix="/messenger-links/telegram", route_class=NoStoreLinkRoute
    )

    @router.post("/challenge")
    async def challenge(request: Request, body: ChallengeCommand):
        return await _execute(
            request, body, lambda s, a: s.create(a, body.operation_key)
        )

    @router.post("/status")
    async def status(request: Request, body: LinkStatus):
        return await _execute(
            request, body, lambda s, a: s.status(a, body.challenge_id)
        )

    @router.post("/confirm")
    async def confirm(request: Request, body: ConfirmCommand):
        return await _execute(
            request,
            body,
            lambda s, a: s.confirm(
                a,
                body.challenge_id,
                body.claim_id,
                body.expected_version,
                body.operation_key,
            ),
        )

    @router.post("/revoke")
    async def revoke(request: Request, body: RevokeCommand):
        return await _execute(
            request,
            body,
            lambda s, a: s.revoke(
                a, body.challenge_id, body.expected_version, body.operation_key
            ),
        )

    return router
