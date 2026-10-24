"""Independent pure HTTP-status classification regression; no database."""

import pytest
from fastapi import HTTPException

from tests.unit.test_native_caller_error_safety import (
    PRIVATE,
    ROUTES,
    fault_response,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("route_class,_unavailable", ROUTES)
@pytest.mark.parametrize("status_kind", ["int-subclass", "object"])
async def test_known_http_code_never_hashes_untrusted_status(
    route_class, _unavailable, status_kind, caplog
):
    conversions = []

    class UnsafeInt(int):
        def __hash__(self):
            conversions.append("hashed")
            raise RuntimeError(PRIVATE)

    class UnsafeStatus:
        def __hash__(self):
            conversions.append("hashed")
            raise RuntimeError(PRIVATE)

    status = UnsafeInt(418) if status_kind == "int-subclass" else UnsafeStatus()
    response = await fault_response(
        route_class,
        HTTPException(
            status_code=status,
            detail="financial_principal_changed",
            headers={"X-Private": PRIVATE},
        ),
    )
    assert (
        response.status_code,
        response.headers.get("Cache-Control"),
        conversions,
    ) == (403, "no-store", [])
    assert response.json() == {"detail": "financial_principal_changed"}
    assert "X-Private" not in response.headers
    assert PRIVATE not in response.text and PRIVATE not in caplog.text
