"""Unavailable selection reads never return a success response."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.selection_api import create_selection_router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [None, LookupError("selection_order_not_found"), ValueError("unavailable")],
)
async def test_unavailable_selection_is_not_a_success_response(failure):
    async def actor(request, init_data, *, platform):
        return AuthenticatedMessengerPrincipal(uuid4(), platform, "123")

    app = FastAPI()
    app.include_router(create_selection_router(actor))
    app.state.config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=False)
    )
    app.state.dispatcher = {
        "selection_view_service": None
        if failure is None
        else SimpleNamespace(view=AsyncMock(side_effect=failure)),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/financial/orders/{uuid4()}/selection",
            json={"init_data": "synthetic"},
        )
    assert response.status_code == (
        404 if isinstance(failure, LookupError) else 503
    )
