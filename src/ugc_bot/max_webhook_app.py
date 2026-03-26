"""Max messenger webhook application.

Entry point for Max bot. Runs as a separate process on port 8003.
Usage: uvicorn ugc_bot.max_webhook_app:app --host 0.0.0.0 --port 8003
"""

import hmac
import logging
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ugc_bot.bot.max.handlers.advertiser_registration import (
    router as adv_reg_router,
)
from ugc_bot.bot.max.handlers.blogger_registration import (
    router as blog_reg_router,
)
from ugc_bot.bot.max.handlers.complaints import router as complaints_router
from ugc_bot.bot.max.handlers.feedback import router as feedback_router
from ugc_bot.bot.max.handlers.instagram_verification import (
    router as ig_verify_router,
)
from ugc_bot.bot.max.handlers.my_orders import router as my_orders_router
from ugc_bot.bot.max.handlers.offer_responses import (
    router as offer_resp_router,
)
from ugc_bot.bot.max.handlers.order_creation import (
    router as order_create_router,
)
from ugc_bot.bot.max.handlers.profile import router as profile_router
from ugc_bot.bot.max.handlers.referral import router as referral_router
from ugc_bot.bot.max.handlers.start import router as start_router
from ugc_bot.bot.max.middleware import resolve_locale
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
max_router.include(start_router)
max_router.include(adv_reg_router)
max_router.include(blog_reg_router)
max_router.include(order_create_router)
max_router.include(profile_router)
max_router.include(my_orders_router)
max_router.include(offer_resp_router)
max_router.include(referral_router)
max_router.include(complaints_router)
max_router.include(feedback_router)
max_router.include(ig_verify_router)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config = load_config()

    if not config.max_bot:
        raise ValueError(
            "MAX_BOT_TOKEN is required for Max webhook app. "
            "Set MAX_BOT_TOKEN environment variable."
        )

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
    app.state.webhook_secret = config.max_bot.webhook_secret or None

    # Register webhook with Max API
    webhook_url = config.max_bot.webhook_url
    subscription_body: dict = {"url": webhook_url}
    if config.max_bot.webhook_secret:
        subscription_body["secret"] = config.max_bot.webhook_secret
    async with http_session.post(
        f"{MAX_API_BASE_URL}/subscriptions",
        json=subscription_body,
        headers={"Authorization": config.max_bot.token},
    ) as resp:
        if resp.status < 300:
            logger.info("Max webhook registered: %s", webhook_url)
        else:
            body = await resp.text()
            raise RuntimeError(
                f"Failed to register Max webhook (HTTP {resp.status}): {body}"
            )

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
    state = request.app.state

    # Verify webhook secret if configured
    webhook_secret = getattr(state, "webhook_secret", None)
    if webhook_secret:
        header_secret = request.headers.get("X-Max-Bot-Api-Secret", "")
        if not hmac.compare_digest(header_secret, webhook_secret):
            logger.warning("Max webhook rejected: invalid secret")
            return JSONResponse({"ok": False}, status_code=403)

    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        logger.warning("Max webhook received non-JSON body")
        return JSONResponse(
            {"ok": False, "error": "invalid json"}, status_code=400
        )

    update_type = data.get("update_type")
    logger.debug("Max webhook payload: %s", data)
    event_adapter: MaxEventAdapter = state.event_adapter

    deps: dict = {
        **state.bot_services,
        "messenger_client": state.messenger_client,
        "config": state.config,
    }

    try:
        if update_type in ("message_created", "bot_started"):
            if update_type == "bot_started":
                incoming = event_adapter.from_bot_started(data)
            else:
                incoming = event_adapter.from_message(data)
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming.chat_id,
                user_id=incoming.user.external_id,
            )
            deps["state_store"] = state_store
            locale = await resolve_locale(
                incoming,
                state.bot_services["user_role_service"],
                state.config.market.default_locale,
            )
            deps["locale"] = locale
            await state.max_router.route_message(incoming, deps)

        elif update_type == "message_callback":
            incoming_cb = event_adapter.from_callback(data)
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming_cb.chat_id,
                user_id=incoming_cb.user.external_id,
            )
            deps["state_store"] = state_store
            locale = await resolve_locale(
                incoming_cb,
                state.bot_services["user_role_service"],
                state.config.market.default_locale,
            )
            deps["locale"] = locale
            await state.max_router.route_callback(incoming_cb, deps)

        else:
            logger.debug("Unhandled Max update type: %s", update_type)

    except Exception:
        logger.exception("Error processing Max update: %s", update_type)
        return JSONResponse({"ok": False, "error": "internal"}, status_code=500)

    return JSONResponse({"ok": True})
