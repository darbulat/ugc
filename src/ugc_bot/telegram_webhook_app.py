"""FastAPI application for Telegram webhook endpoint.

Enables scalable bot deployment: multiple app replicas behind nginx
can receive updates via webhook (no polling conflict).
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ugc_bot.app import build_dispatcher, create_storage
from ugc_bot.application.geography import get_cities_list_for_miniapp
from ugc_bot.config import load_config
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.infrastructure.messenger.telegram.payments import (
    TelegramPaymentProvider,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.metrics.collector import (
    record_http_request,
    record_telegram_webhook_invalid,
    record_telegram_webhook_received,
)
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)

_MAX_WEBHOOK_RETRIES = 5
_MAX_CONCURRENT_WEBHOOK_UPDATES = 100


async def _set_webhook_with_retry(
    bot: Bot, webhook_url: str, secret_token: str | None
) -> None:
    """Register webhook with retry on Telegram flood control (429)."""
    for attempt in range(_MAX_WEBHOOK_RETRIES):
        try:
            await bot.set_webhook(webhook_url, secret_token=secret_token)
            return
        except TelegramRetryAfter as exc:
            if attempt == _MAX_WEBHOOK_RETRIES - 1:
                logger.error(
                    "set_webhook failed after %d retries (flood control)",
                    _MAX_WEBHOOK_RETRIES,
                    extra={"retry_after": exc.retry_after},
                )
                raise
            wait_sec = exc.retry_after + 1
            logger.warning(
                "Telegram flood control on set_webhook, retrying in %ds",
                wait_sec,
                extra={"retry_after": exc.retry_after, "attempt": attempt + 1},
            )
            await asyncio.sleep(wait_sec)


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

    secret = config.webhook.webhook_secret.strip()
    if not secret:
        raise ValueError(
            "WEBHOOK_SECRET is required for production webhook mode. "
            "Set a secure random token for X-Telegram-Bot-Api-Secret-Token."
        )

    storage = None
    bot = None
    try:
        storage = await create_storage(config)
        dispatcher = build_dispatcher(config, storage=storage)
        bot = Bot(token=config.bot.bot_token)
        messenger_client = TelegramMessengerClient(bot)
        event_adapter = TelegramEventAdapter()
        payment_provider = TelegramPaymentProvider(bot)

        webhook_url = f"{base_url}/webhook/telegram"
        await _set_webhook_with_retry(bot, webhook_url, secret)
        logger.info("Webhook registered", extra={"url": webhook_url})

        dispatcher["messenger_client"] = messenger_client
        dispatcher["event_adapter"] = event_adapter
        dispatcher["payment_provider"] = payment_provider

        app.state.config = config
        app.state.dispatcher = dispatcher
        app.state.bot = bot
        app.state.storage = storage
        app.state.webhook_semaphore = asyncio.Semaphore(
            _MAX_CONCURRENT_WEBHOOK_UPDATES
        )

        yield
    finally:
        if bot is not None:
            with suppress(Exception):
                await bot.delete_webhook()
            await bot.session.close()
        if storage is not None and hasattr(storage, "close"):
            await storage.close()


app = FastAPI(title="Telegram Webhook", lifespan=_lifespan)


@app.middleware("http")
async def _http_metrics_middleware(request: Request, call_next):
    """Record HTTP request metrics (RED method)."""
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except HTTPException as exc:
        status_code = exc.status_code
        raise
    except Exception:
        status_code = 500
        raise
    finally:
        duration = time.perf_counter() - start
        path = request.url.path or "/"
        record_http_request(
            method=request.method,
            path=path,
            status_code=status_code,
            duration_seconds=duration,
        )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Log unhandled exceptions and return 500 (or 200 for webhooks)."""
    logger.exception(
        "Unhandled exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"service": "ugc-bot", "path": request.url.path},
    )
    if request.url.path.startswith("/webhook/"):
        return JSONResponse(
            content={"status": "error", "message": "Internal error"},
            status_code=200,
        )
    return JSONResponse(
        content={"detail": "Internal server error"},
        status_code=500,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Lightweight health check."""
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics."""
    body = generate_latest()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


_MINIAPP_DIR = Path(__file__).resolve().parent / "miniapp"


@app.get("/miniapp/cities.json")
async def miniapp_cities_json() -> JSONResponse:
    """Return list of cities for Mini App city picker (id + label)."""
    cities = get_cities_list_for_miniapp()
    return JSONResponse(
        content=cities,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/miniapp/city-picker")
async def miniapp_city_picker() -> FileResponse:
    """Serve Mini App HTML page for city selection."""
    path = _MINIAPP_DIR / "city_picker.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Mini App not found")
    return FileResponse(path, media_type="text/html")


@app.post("/webhook/telegram")
async def handle_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> dict[str, str]:
    """Receive updates from Telegram. Process in background, return 200."""
    config = request.app.state.config
    secret = config.webhook.webhook_secret.strip()
    if not secret or x_telegram_bot_api_secret_token != secret:
        logger.warning("Invalid or missing webhook secret token")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    dispatcher: Dispatcher = request.app.state.dispatcher
    bot: Bot = request.app.state.bot

    try:
        data = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON in webhook request", exc_info=exc)
        record_telegram_webhook_invalid()
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    try:
        update = Update.model_validate(data, context={"bot": bot})
    except Exception as exc:
        logger.warning("Invalid Update payload", exc_info=exc)
        record_telegram_webhook_invalid()
        raise HTTPException(status_code=400, detail="Invalid update") from exc

    record_telegram_webhook_received()

    semaphore = getattr(request.app.state, "webhook_semaphore", None)
    if semaphore is None:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WEBHOOK_UPDATES)

    async def _process_update_safely() -> None:
        """Process webhook update with bounded concurrency and error logging."""
        async with semaphore:
            try:
                await dispatcher.feed_update(bot, update)
            except Exception:
                logger.exception(
                    "Error processing webhook update",
                    extra={"update_id": getattr(update, "update_id", None)},
                )

    asyncio.create_task(_process_update_safely())
    return {"status": "ok"}
