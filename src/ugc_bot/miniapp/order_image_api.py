"""Signed uploads and owner-only previews for original order JPEGs."""

import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class OrderImageRoute(_NativeCallerRoute):
    prefix = "image"
    codes = SHARED_CODES | {
        "image_owner_required": 403,
        "image_not_found": 404,
        "image_expired": 422,
        "image_invalid": 422,
        "image_jpeg_required": 422,
        "image_dimensions": 422,
        "image_too_large": 422,
        "image_integrity_error": 503,
        "image_upload_unavailable": 503,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


class ImageUpload(SignedMiniAppRequest):
    image_base64: str = Field(min_length=4, max_length=6_666_668)


class ImageRead(SignedMiniAppRequest):
    image_token: UUID


async def _context(request, body, resolve):
    if request.query_params:
        raise HTTPException(422, "image_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    service = request.app.state.dispatcher.get("order_image_service")
    if service is None:
        raise HTTPException(503, "image_upload_unavailable")
    return principal, service


async def _execute(request, body, action, resolve):
    principal, service = await _context(request, body, resolve)
    try:
        return await action(principal, service)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except binascii.Error as exc:
        raise HTTPException(422, "image_request_invalid") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def create_order_image_router(resolve: FinancialPrincipalResolver) -> APIRouter:
    router = APIRouter(prefix="/orders/images", route_class=OrderImageRoute)

    @router.post("")
    async def upload(request: Request, body: ImageUpload):
        async def action(principal, service):
            data = base64.b64decode(body.image_base64, validate=True)
            value = await service.upload(
                principal.user_id, data, principal=principal
            )
            return {
                "image_token": str(value.token),
                "byte_count": value.byte_count,
                "width": 1080,
                "height": 1080,
                "format": "JPEG",
            }

        return await _execute(request, body, action, resolve)

    @router.post("/content")
    async def content(request: Request, body: ImageRead):
        async def action(principal, service):
            data = await service.content(
                principal.user_id, body.image_token, principal=principal
            )
            return {
                "image_base64": base64.b64encode(data).decode("ascii"),
                "content_type": "image/jpeg",
            }

        return await _execute(request, body, action, resolve)

    return router
