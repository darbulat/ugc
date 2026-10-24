"""Finite social-only errors; arbitrary exceptions are never stringified."""

from types import MappingProxyType

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

SOCIAL_CODES = MappingProxyType(
    {
        "financial_session_invalid": 401,
        "existing_financial_account_required": 404,
        "financial_principal_changed": 403,
        "financial_unavailable": 503,
        "social_account_unavailable": 403,
        "social_request_invalid": 422,
        "social_creator_profile_required": 400,
        "social_instagram_verification_required": 400,
        "social_profile_url_invalid": 400,
        "social_account_owner_mismatch": 400,
        "social_unavailable": 503,
    }
)


def _failure(code: object) -> JSONResponse:
    safe = (
        code
        if type(code) is str and code in SOCIAL_CODES
        else "social_unavailable"
    )
    return JSONResponse({"detail": safe}, status_code=SOCIAL_CODES[safe])


class NoStoreSocialRoute(APIRoute):
    """Cover validation, context, transaction exit and response encoding."""

    def get_route_handler(self):
        original = APIRoute.get_route_handler(self)

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = _failure("social_request_invalid")
            except HTTPException as error:
                response = _failure(error.detail)
            except (ValueError, PermissionError) as error:
                response = _failure(
                    error.args[0] if len(error.args) == 1 else None
                )
            except Exception:
                response = _failure(None)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler
