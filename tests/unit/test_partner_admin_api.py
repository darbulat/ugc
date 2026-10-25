"""Wire fields cannot grant actor authority or expose signed data."""

from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_partner_admin_service import (
    ADMIN,
    CLIENT,
    LEAD,
    NEW,
    OLD,
    PRINCIPAL,
    service,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.override_ports import OverrideUser
from ugc_bot.miniapp.partner_admin_api import create_partner_admin_router


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
async def test_current_admin_replay_and_strict_body_authority():
    repository, app_service = service()

    async def resolve(request, init_data, *, platform):
        if init_data == "invalid":
            return None
        return (
            PRINCIPAL
            if init_data == "admin"
            else AuthenticatedMessengerPrincipal(
                CLIENT, "telegram", str(CLIENT)
            )
        )

    app = FastAPI()
    app.include_router(create_partner_admin_router(resolve))
    app.state.dispatcher = {
        "partner_admin_service": app_service,
        "transaction_manager": Transactions(),
    }
    body = {
        "init_data": "admin",
        "operation_key": "wire:1",
        "lead_id": str(LEAD),
        "expected_version": 0,
        "action": "reject",
        "manager_ids": [],
        "reason": "No manager available",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:

        async def queue(page, status, *, session):
            return dict(entries=[], page=page, has_more=False)

        repository.queue_leads = queue
        assert (
            await client.post(
                "/admin/partners/context", json={"init_data": "admin"}
            )
        ).status_code == 200
        assert (
            await client.post(
                "/admin/partners/leads", json={"init_data": "admin"}
            )
        ).status_code == 200
        correction = dict(
            init_data="admin",
            operation_key="fix",
            referred_id=str(CLIENT),
            expected_referrer_id=str(OLD),
            referrer_id=str(NEW),
            reason="Техническое исправление",
        )
        assert (
            await client.post(
                "/admin/partners/binding-command", json=correction
            )
        ).status_code == 200
        assert (
            await client.post(
                "/admin/partners/context?actor_id=forged",
                json={"init_data": "admin"},
            )
        ).status_code == 422
        assert (
            await client.post(
                "/admin/partners/context", json={"init_data": "invalid"}
            )
        ).status_code == 401
        result = await client.post("/admin/partners/lead-command", json=body)
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["actor_id"] == str(ADMIN)
        assert result.json()["source_state"] == "requested_unpaid"
        assert (
            await client.post("/admin/partners/lead-command", json=body)
        ).json() == result.json()
        denied = await client.post(
            "/admin/partners/lead-command", json={**body, "init_data": "member"}
        )
        assert denied.status_code == 403
        forged = await client.post(
            "/admin/partners/lead-command",
            json={**body, "actor_id": str(ADMIN), "reason": "PRIVATE REQUEST"},
        )
        assert forged.status_code == 422 and "PRIVATE" not in forged.text
        repository.users[ADMIN] = OverrideUser(
            ADMIN, "active", False, "admin-native"
        )
        assert (
            await client.post(
                "/admin/partners/context", json={"init_data": "admin"}
            )
        ).status_code == 403
        assert (
            await client.post("/admin/partners/lead-command", json=body)
        ).status_code == 403
        app.state.dispatcher = {}
        assert (
            await client.post(
                "/admin/partners/context", json={"init_data": "admin"}
            )
        ).status_code == 503
