"""Real webhook mounts serve the campaign controller without lifespan."""

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["telegram_webhook_app", "max_webhook_app"])
async def test_real_webhook_mount_serves_campaign_settings_controller(module):
    import importlib

    app = importlib.import_module(f"ugc_bot.{module}").app
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ugc_bot/miniapp/umc-campaigns.js"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/miniapp/umc-campaigns.js")
    assert response.status_code == 200
    assert response.content == path.read_bytes()
