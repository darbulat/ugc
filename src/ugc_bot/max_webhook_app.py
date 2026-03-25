"""Max messenger webhook application.

Entry point for Max bot. Runs as a separate process on port 8003.
Usage: uvicorn ugc_bot.max_webhook_app:app --host 0.0.0.0 --port 8003
"""

import logging
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter
from ugc_bot.infrastructure.messenger.max.client import (
    MAX_API_BASE_URL,
    MaxMessengerClient,
)
from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

logger = logging.getLogger(__name__)

max_router = MaxRouter()

# Import Max handlers here (registers routes on import)
# from ugc_bot.bot.max.handlers import start as _start  # noqa: F401


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config = load_config()

    if not config.max_bot:
        logger.error("MAX_BOT_TOKEN not configured, exiting")
        yield
        return

    redis = Redis.from_url(config.redis.redis_url, decode_responses=True)
    http_session = aiohttp.ClientSession()

    container = Container(config)
    bot_services = container.build_bot_services()

    messenger_client = MaxMessengerClient(
        token=config.max_bot.token, session=http_session
    )
    event_adapter = MaxEventAdapter()

    app.state.config = config
    app.state.redis = redis
    app.state.bot_services = bot_services
    app.state.messenger_client = messenger_client
    app.state.event_adapter = event_adapter
    app.state.container = container
    app.state.max_router = max_router

    # Register webhook with Max API
    webhook_url = config.max_bot.webhook_url
    try:
        async with http_session.post(
            f"{MAX_API_BASE_URL}/subscriptions",
            json={"url": webhook_url},
            headers={"Authorization": config.max_bot.token},
        ) as resp:
            if resp.status < 300:
                logger.info("Max webhook registered: %s", webhook_url)
            else:
                logger.error(
                    "Failed to register Max webhook: %s", await resp.text()
                )
    except Exception:
        logger.exception("Error registering Max webhook")

    logger.info("Max webhook app started")

    yield

    await http_session.close()
    await redis.aclose()
    await container.dispose()


app = FastAPI(lifespan=_lifespan)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhook/max")
async def handle_max_webhook(request: Request) -> JSONResponse:
    data = await request.json()
    update_type = data.get("update_type")
    state = request.app.state
    event_adapter: MaxEventAdapter = state.event_adapter

    deps = {
        **state.bot_services,
        "messenger_client": state.messenger_client,
        "config": state.config,
    }

    try:
        if update_type == "message_created":
            incoming = event_adapter.from_message(data)
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming.chat_id,
                user_id=incoming.user.external_id,
            )
            deps["state_store"] = state_store
            await state.max_router.route_message(incoming, deps)

        elif update_type == "message_callback":
            incoming_cb = event_adapter.from_callback(data)
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming_cb.chat_id,
                user_id=incoming_cb.user.external_id,
            )
            deps["state_store"] = state_store
            await state.max_router.route_callback(incoming_cb, deps)

        else:
            logger.debug("Unhandled Max update type: %s", update_type)

    except Exception:
        logger.exception("Error processing Max update: %s", update_type)

    return JSONResponse({"ok": True})
