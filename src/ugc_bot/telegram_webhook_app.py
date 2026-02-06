"""FastAPI application for Telegram webhook endpoint.

Enables scalable bot deployment: multiple app replicas behind nginx
can receive updates via webhook (no polling conflict).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ugc_bot.app import build_dispatcher, create_storage
from ugc_bot.config import load_config
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize bot, dispatcher, storage and register webhook on startup."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    log_startup_info(logger=logger, service_name="ugc-bot", config=config)

    base_url = config.webhook.webhook_base_url
    if not base_url:
        raise ValueError(
            "WEBHOOK_BASE_URL is required for webhook mode. "
            "Set it to your public HTTPS URL (e.g. https://bot.example.com)"
        )

    storage = await create_storage(config)
    dispatcher = build_dispatcher(config, storage=storage)
    bot = Bot(token=config.bot.bot_token)

    webhook_url = f"{base_url}/webhook/telegram"
    secret = config.webhook.webhook_secret.strip() or None
    await bot.set_webhook(webhook_url, secret_token=secret)
    logger.info("Webhook registered", extra={"url": webhook_url})

    app.state.dispatcher = dispatcher
    app.state.bot = bot
    app.state.storage = storage

    yield

    await bot.delete_webhook()
    if hasattr(storage, "close"):
        await storage.close()
    await bot.session.close()


app = FastAPI(title="Telegram Webhook", lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Lightweight health check."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics."""
    body = generate_latest()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


@app.post("/webhook/telegram")
async def handle_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> dict[str, str]:
    """Receive updates from Telegram. Process in background, return 200."""
    config = load_config()
    secret = config.webhook.webhook_secret.strip()
    if secret and x_telegram_bot_api_secret_token != secret:
        logger.warning("Invalid or missing webhook secret token")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    dispatcher: Dispatcher = request.app.state.dispatcher
    bot: Bot = request.app.state.bot

    try:
        data = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON in webhook request", exc_info=exc)
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    try:
        update = Update.model_validate(data, context={"bot": bot})
    except Exception as exc:
        logger.warning("Invalid Update payload", exc_info=exc)
        raise HTTPException(status_code=400, detail="Invalid update") from exc

    asyncio.create_task(dispatcher.feed_update(bot, update))
    return {"status": "ok"}
