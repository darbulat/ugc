"""Signed customer endpoint validation, identity and controlled errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.client_followup_api import create_client_followup_router
from ugc_bot.miniapp.order_support_api import create_order_support_router
from ugc_bot.miniapp.service_lead_api import create_service_lead_router


@pytest.fixture
def api():
    app = FastAPI()
    actor = AuthenticatedMessengerPrincipal(uuid4(), "telegram", "123")
    resolve = AsyncMock(return_value=actor)
    support = SimpleNamespace(
        create=AsyncMock(
            return_value={"request_id": str(uuid4()), "state": "new"}
        ),
        list=AsyncMock(return_value=[]),
        update_status=AsyncMock(),
    )
    leads = SimpleNamespace(
        create=AsyncMock(return_value={"state": "new"}),
        catalog=AsyncMock(return_value={"services": []}),
    )
    follow = SimpleNamespace(
        register_brief=AsyncMock(),
        record_activity=AsyncMock(return_value={"generation": 1}),
        state=AsyncMock(return_value=None),
        optout=AsyncMock(),
    )
    app.state.dispatcher = {
        "order_support_service": support,
        "service_lead_service": leads,
        "client_followup_service": follow,
    }
    for factory in (
        create_order_support_router,
        create_service_lead_router,
        create_client_followup_router,
    ):
        app.include_router(factory(resolve))
    return app, actor, resolve


@pytest.mark.asyncio
async def test_signed_routes_forward_trusted_principal_and_typed_body(api):
    app, actor, resolve = api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        support = dict(
            init_data="signed",
            order_id=str(uuid4()),
            operation_key=" key ",
            reason=" Help ",
            contact_reference="@me",
        )
        response = await client.post("/customer/support", json=support)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        call = app.state.dispatcher["order_support_service"].create.call_args
        assert (
            call.args[0] == actor.user_id
            and call.args[1].operation_key == "key"
        )
        assert call.kwargs["principal"] == actor
        for path, body in [
            ("/customer/support/list", {"order_id": support["order_id"]}),
            (
                "/customer/support/status",
                {"request_id": str(uuid4()), "state": "resolved"},
            ),
            ("/customer/services/catalog", {}),
            (
                "/customer/services",
                dict(
                    service_code="regular_search",
                    operation_key="x",
                    contact_reference="@me",
                    source="miniapp",
                    parameters={},
                    consent=True,
                ),
            ),
            ("/customer/followups/activity", {"event": "menu"}),
            ("/customer/followups/state", {}),
            ("/customer/followups/optout", {}),
        ]:
            response = await client.post(
                path, json={"init_data": "signed", **body}
            )
            assert response.status_code == 200, (path, response.text)


@pytest.mark.asyncio
async def test_followup_brief_preserves_its_purchase_intent(api):
    app, actor, _ = api
    intent_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post(
            "/customer/followups/activity",
            json={
                "init_data": "signed",
                "event": "brief_opened",
                "intent_id": str(intent_id),
            },
        )
    assert response.status_code == 200
    call = app.state.dispatcher[
        "client_followup_service"
    ].record_activity.call_args
    assert call.kwargs["principal"] == actor
    assert call.kwargs["intent_id"] == intent_id


@pytest.mark.asyncio
async def test_followup_registers_intent_for_authenticated_customer(api):
    app, actor, _ = api
    intent_id = uuid4()
    app.state.dispatcher[
        "client_followup_service"
    ].register_brief.return_value = intent_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        response = await client.post(
            "/customer/followups/register-brief",
            json={"init_data": "signed"},
        )
    assert response.status_code == 200
    app.state.dispatcher[
        "client_followup_service"
    ].register_brief.assert_awaited_once_with(actor.user_id, principal=actor)
    assert response.json()["intent_id"] == str(intent_id)


@pytest.mark.asyncio
async def test_error_boundary_missing_service_bad_identity_query_and_contract(
    api,
):
    app, actor, resolve = api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        assert (
            await client.post(
                "/customer/followups/activity",
                json={"init_data": "signed", "event": "paid"},
            )
        ).status_code == 422
        assert (
            await client.post(
                "/customer/followups/state?user_id=other",
                json={"init_data": "signed"},
            )
        ).status_code == 422
        resolve.return_value = actor.user_id
        assert (
            await client.post(
                "/customer/followups/state", json={"init_data": "signed"}
            )
        ).status_code == 401
        resolve.return_value = actor
        app.state.dispatcher[
            "client_followup_service"
        ].state.side_effect = PermissionError("active_advertiser_required")
        assert (
            await client.post(
                "/customer/followups/state", json={"init_data": "signed"}
            )
        ).status_code == 403
        app.state.dispatcher["client_followup_service"] = None
        assert (
            await client.post(
                "/customer/followups/state", json={"init_data": "signed"}
            )
        ).status_code == 503
