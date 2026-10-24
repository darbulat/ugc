"""The real webhook apps serve the own-client controller without lifespan."""

from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["telegram_webhook_app", "max_webhook_app"])
@pytest.mark.parametrize(
    "asset", ["umc-selection.js", "umc-checkout.js", "umc-messenger-linking.js"]
)
async def test_real_webhook_mount_serves_selection_controller(module, asset):
    import importlib

    app = importlib.import_module(f"ugc_bot.{module}").app
    path = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp" / asset
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/miniapp/" + asset)
    assert response.status_code == 200
    assert response.content == path.read_bytes()
