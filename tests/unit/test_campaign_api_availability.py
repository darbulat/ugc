"""Configuration failures produce explicit signed API errors."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.miniapp.campaign_api import create_campaign_router


@asynccontextmanager
async def transaction():
    yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status",
    [
        (PermissionError("role lost"), 403),
        (LookupError("missing actor"), 404),
        (CampaignConflict("stale"), 409),
        (ValueError("invalid configuration"), 422),
        (ValueError("campaign_foundation_unavailable"), 503),
        (None, 503),
    ],
)
async def test_signed_context_errors_are_distinct(error, status):
    async def resolve(request, init_data, *, platform):
        return uuid4()

    async def view(*args, **kwargs):
        raise error

    app = FastAPI()
    app.include_router(create_campaign_router(resolve))
    app.state.dispatcher = {
        "campaign_service": SimpleNamespace(view=view) if error else None,
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/campaigns/settings",
            json={
                "init_data": "already validated synthetic envelope",
                "platform": "max",
            },
        )
        assert result.status_code == status
