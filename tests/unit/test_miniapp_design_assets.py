"""Verify the production ASGI mounts serve the packaged Mini App assets."""

from pathlib import Path

import pytest

MINIAPP = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["telegram_webhook_app", "max_webhook_app"])
async def test_real_webhook_apps_serve_packaged_frontend(module: str) -> None:
    import importlib

    import httpx

    app = importlib.import_module(f"ugc_bot.{module}").app
    # ASGITransport omits lifespan and does not connect to live services.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for path in (
            "app.html",
            "max_app.html",
            "umc-app.css",
            "umc-shell.js",
            "umc-collaborations.js",
            "umc-partner.js",
            "design-system/fonts/fonts.css",
            "design-system/tokens.css",
            "design-system/umc-ui.css",
            "design-system/assets/umc-logo.png",
            "design-system/assets/pixel-edge.svg",
            "design-system/fonts/oswald-latin.woff2",
            "design-system/fonts/oswald-cyrillic.woff2",
            "design-system/fonts/plex-sans-latin.woff2",
            "design-system/fonts/plex-sans-cyrillic.woff2",
        ):
            response = await client.get(f"/miniapp/{path}")
            assert response.status_code == 200, path
            assert response.content == (MINIAPP / path).read_bytes()
