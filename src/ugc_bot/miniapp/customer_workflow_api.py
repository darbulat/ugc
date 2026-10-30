"""No-store boundary and principal revalidation for customer workflows."""

from fastapi import HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.native_caller_errors import (
    SHARED_CODES,
    _NativeCallerRoute,
)


class CustomerWorkflowRoute(_NativeCallerRoute):
    prefix = "customer"
    codes = SHARED_CODES | {
        "active_advertiser_required": 403,
        "active_admin_required": 403,
        "customer_order_forbidden": 403,
        "customer_blogger_forbidden": 403,
        "customer_request_not_found": 404,
        "support_state_invalid": 422,
        "followup_event_invalid": 422,
        "customer_disabled": 503,
    }
    http_pairs = {(code, status): status for code, status in codes.items()}


async def context(request: Request, body, resolve, key: str):
    if request.query_params:
        raise HTTPException(422, "customer_request_invalid")
    principal = await resolve(request, body.init_data, platform=body.platform)
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    service = request.app.state.dispatcher.get(key)
    if service is None:
        raise HTTPException(503, "customer_disabled")
    return principal, service
