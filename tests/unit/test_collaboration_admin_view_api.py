"""A dedicated admin review preserves ordinary collaboration privacy."""

from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_work_dispute_resolution import disputed
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.collaboration_api import create_collaboration_router


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_admin_view_preserves_party_privacy_and_current_authority(
    platform,
):
    service, repo, scope, _, _, admin, _ = await disputed()
    repo.actors[admin] = replace(
        repo.actors[admin], telegram_id="123", max_id="123"
    )
    principal = AuthenticatedMessengerPrincipal(admin, platform, "123")

    async def resolve(request, init_data, *, platform):
        return principal if init_data == "signed" else None

    app = FastAPI()
    app.state.config = NS(financial=NS(core_enabled=True))
    app.state.dispatcher = dict(
        collaboration_service=service, transaction_manager=repo
    )
    app.include_router(create_collaboration_router(resolve))
    body = dict(init_data="signed", platform=platform)
    path = f"/collaborations/admin/{scope.assignment_id}/view"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
        assert response.status_code == 200, response.text
        assert set(response.json()["allowed_actions"]) == {
            "resolve_success",
            "resolve_failure",
        }
        assert response.json()["actor_id"] == str(admin)
        assert response.headers["cache-control"] == "no-store"
        ordinary = f"/collaborations/{scope.assignment_id}/status"
        assert (await client.post(ordinary, json=body)).status_code == 403
        assert (
            await client.post(path + "?actor=forged", json=body)
        ).status_code == 422
        assert (
            await client.post(path, json=dict(body, init_data="invalid"))
        ).status_code == 401
        assert (
            await client.post(
                f"/collaborations/admin/{uuid4()}/view", json=body
            )
        ).status_code == 404
        repo.actors[admin] = replace(repo.actors[admin], is_admin=False)
        assert (await client.post(path, json=body)).status_code == 403
