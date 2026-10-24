"""Real shared route errors never convert private exception values.

The endpoints are synthetic faults; the existing production route classes and
ASGI response boundary are exercised without a service, engine or database.
"""

import httpx
import pytest
from fastapi import APIRouter, FastAPI, HTTPException

from ugc_bot.miniapp.native_caller_errors import (
    NoStoreCollaborationRoute,
    NoStoreIntakeRoute,
    NoStorePartnerRoute,
    NoStoreSelectionRoute,
    NoStoreSummaryRoute,
)

ROUTES = [
    pytest.param(NoStoreIntakeRoute, "intake_unavailable", id="intake"),
    pytest.param(
        NoStoreCollaborationRoute,
        "collaboration_unavailable",
        id="collaboration",
    ),
    pytest.param(NoStorePartnerRoute, "partner_unavailable", id="partner"),
    pytest.param(
        NoStoreSelectionRoute, "selection_unavailable", id="selection"
    ),
    pytest.param(NoStoreSummaryRoute, "summary_unavailable", id="summary"),
]
PRIVATE = "synthetic-private-exception-value"


async def fault_response(route_class, error):
    router = APIRouter(route_class=route_class)

    @router.post("/fault")
    async def fault():
        raise error

    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        return await client.post("/fault")


@pytest.mark.asyncio
@pytest.mark.parametrize("route_class,unavailable", ROUTES)
@pytest.mark.parametrize("error_kind", [ValueError, PermissionError])
@pytest.mark.parametrize("conversion", ["raise", "spoof-known-code"])
async def test_shared_error_boundary_never_converts_exception(
    route_class, unavailable, error_kind, conversion, caplog
):
    # A str(error) classifier either escapes the handler or trusts spoofed text.
    conversions = []

    class UnsafeError(error_kind):
        def __str__(self):
            conversions.append("converted")
            if conversion == "raise":
                raise RuntimeError(PRIVATE)
            return "financial_principal_changed"

    response = await fault_response(route_class, UnsafeError(PRIVATE))
    assert (response.status_code, response.headers.get("Cache-Control")) == (
        503,
        "no-store",
    )
    assert response.json() == {"detail": unavailable}
    assert response.headers["Cache-Control"] == "no-store"
    assert conversions == []
    assert PRIVATE not in response.text
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route_class,unavailable", ROUTES)
@pytest.mark.parametrize("error_kind", [ValueError, PermissionError])
async def test_shared_error_boundary_never_converts_non_string_argument(
    route_class, unavailable, error_kind, caplog
):
    conversions = []

    class UnsafeArgument:
        def __str__(self):
            conversions.append("converted")
            raise RuntimeError(PRIVATE)

    response = await fault_response(route_class, error_kind(UnsafeArgument()))
    assert (response.status_code, response.headers.get("Cache-Control")) == (
        503,
        "no-store",
    )
    assert response.json() == {"detail": unavailable}
    assert response.headers["Cache-Control"] == "no-store"
    assert conversions == []
    assert PRIVATE not in response.text
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route_class,unavailable", ROUTES)
async def test_shared_known_plain_string_domain_code_keeps_public_status(
    route_class, unavailable
):
    response = await fault_response(
        route_class, ValueError("financial_principal_changed")
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "financial_principal_changed"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_collaboration_scoped_not_found_keeps_existing_http_status():
    response = await fault_response(
        NoStoreCollaborationRoute,
        HTTPException(status_code=404, detail="collaboration_not_found"),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "collaboration_not_found"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("route_class,unavailable", ROUTES)
@pytest.mark.parametrize("detail_kind", ["string-subclass", "object"])
async def test_shared_error_boundary_never_uses_unsafe_http_detail(
    route_class, unavailable, detail_kind, caplog
):
    conversions = []

    class UnsafeString(str):
        def __hash__(self):
            conversions.append("hashed")
            raise RuntimeError(PRIVATE)

    class UnsafeDetail:
        def __eq__(self, other):
            conversions.append("compared")
            raise RuntimeError(PRIVATE)

    detail = (
        UnsafeString(PRIVATE)
        if detail_kind == "string-subclass"
        else UnsafeDetail()
    )
    response = await fault_response(
        route_class,
        HTTPException(
            status_code=418, detail=detail, headers={"X-Private": PRIVATE}
        ),
    )
    assert (response.status_code, response.headers.get("Cache-Control")) == (
        503,
        "no-store",
    )
    assert response.json() == {"detail": unavailable}
    assert "X-Private" not in response.headers
    assert conversions == []
    assert PRIVATE not in response.text
    assert PRIVATE not in caplog.text
