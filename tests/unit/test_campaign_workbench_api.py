"""Signed settings advertise only the installed, mounted draft capability."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.miniapp.campaign_api import create_campaign_router


@asynccontextmanager
async def transaction():
    yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "installed,active,enabled,expected",
    [
        (True, True, True, (True, True, True)),
        (True, False, True, (True, False, False)),
        (True, True, False, (True, False, False)),
        (False, True, True, (False, False, False)),
    ],
)
async def test_settings_capabilities_keep_history_when_creation_is_unavailable(
    installed, active, enabled, expected
):
    async def resolve(request, init_data, *, platform):
        return "10000000-0000-4000-8000-000000000001"

    async def view(actor, *, session):
        return {
            "actor_id": actor,
            "can_admin": True,
            "publisher": {"active": active},
            "policy": {"enabled": enabled},
        }

    app = FastAPI()
    app.include_router(create_campaign_router(resolve))
    methods = SimpleNamespace(
        list_drafts=view,
        detail=view,
        save_draft=view,
        preview=view,
        operation_status=view,
    )
    app.state.dispatcher = {
        "transaction_manager": SimpleNamespace(transaction=transaction),
        "campaign_service": SimpleNamespace(view=view),
        "campaign_review_service": methods if installed else None,
        "campaign_audience_service": methods if installed else None,
        # Unmounted services cannot imply an exposed HTTP capability.
        "campaign_submission_service": methods,
        "campaign_moderation_service": methods,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/campaigns/settings",
            json={"init_data": "signed-boundary", "platform": "max"},
        )
    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert (
        tuple(
            capabilities[name]
            for name in ("read_own_drafts", "save_draft", "preview_audience")
        )
        == expected
    )
    assert capabilities["read_own_operations"] is installed
    assert all(
        capabilities[name] is False
        for name in (
            "submit_campaign",
            "cancel_campaign",
            "read_admin_queue",
            "review_campaign",
        )
    )
