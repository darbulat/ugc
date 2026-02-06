"""FastAPI application for Instagram webhook endpoint."""

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI application.

    Logs version and sanitized config on server startup.
    This runs when the app is served by Uvicorn (including docker-compose),
    where `main()` is typically not executed.
    """
    # Startup
    config = load_config()
    log_startup_info(
        logger=logger, service_name="instagram-webhook", config=config
    )
    yield
    # Shutdown (if needed in the future)


app = FastAPI(title="Instagram Webhook", lifespan=lifespan)


def _verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Verify webhook signature using SHA256."""
    if not signature.startswith("sha256="):
        return False
    expected_signature = signature[7:]  # Remove "sha256=" prefix
    computed = hmac.new(
        app_secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, expected_signature)


@app.get("/health")
async def health() -> dict[str, str]:
    """Lightweight health check for webhook app."""

    return {"status": "ok"}


@app.get("/webhook/instagram")
async def verify_webhook(request: Request) -> Response:
    """Handle webhook verification request from Meta."""
    config = load_config()

    # FastAPI: query params with dots; use request.query_params
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")

    if hub_mode != "subscribe":
        logger.warning("Invalid hub.mode in verification request")
        raise HTTPException(status_code=400, detail="Invalid mode")

    if hub_verify_token != config.instagram.instagram_webhook_verify_token:
        logger.warning("Invalid verify token in verification request")
        raise HTTPException(status_code=403, detail="Invalid verify token")

    if not hub_challenge:
        logger.warning("Missing hub.challenge in verification request")
        raise HTTPException(status_code=400, detail="Missing challenge")

    logger.info("Webhook verification successful")
    return PlainTextResponse(content=hub_challenge)


@app.post("/webhook/instagram")
async def handle_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Handle webhook event notifications from Instagram."""
    config = load_config()

    # Read raw payload for signature verification
    payload_bytes = await request.body()

    # Verify signature if app secret is configured
    if config.instagram.instagram_app_secret:
        if not x_hub_signature_256:
            logger.warning("Missing X-Hub-Signature-256 header")
            raise HTTPException(
                status_code=400, detail="Missing signature header"
            )

        if not _verify_signature(
            payload_bytes,
            x_hub_signature_256,
            config.instagram.instagram_app_secret,
        ):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse JSON payload
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON payload", exc_info=exc)
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    logger.info("Received Instagram webhook", extra={"payload": payload})

    # Process webhook events
    try:
        container = Container(config)
        verification_service = container.build_instagram_verification_service()
        await _process_webhook_events(payload, verification_service, config)
    except Exception as exc:
        logger.exception("Error processing webhook events", exc_info=exc)
        # Still return 200 to prevent retries for processing errors
        return {"status": "error", "message": str(exc)}

    return {"status": "ok"}


async def _notify_user_verification_success(
    user_id: UUID,
    verification_service: InstagramVerificationService,
    config: AppConfig,
) -> None:
    """Send Telegram notification to user about successful verification."""
    try:
        from aiogram import Bot

        from ugc_bot.bot.handlers.keyboards import blogger_menu_keyboard

        (
            user,
            blogger_profile,
        ) = await verification_service.get_notification_recipient(user_id)
        if user is None:
            logger.warning(
                "User not found for verification notification",
                extra={"user_id": user_id},
            )
            return

        if not user.external_id.isdigit():
            logger.warning(
                "User external_id is not a Telegram chat id",
                extra={"user_id": user_id, "external_id": user.external_id},
            )
            return

        confirmed = blogger_profile.confirmed if blogger_profile else False

        bot = Bot(token=config.bot.bot_token)
        try:
            await bot.send_message(
                chat_id=int(user.external_id),
                text=(
                    "Instagram подтверждён ✅. "
                    "Бренды могут отправлять предложения."
                ),
                reply_markup=blogger_menu_keyboard(confirmed=confirmed),
            )
        finally:
            await bot.session.close()
    except Exception as exc:
        logger.exception(
            "Error sending verification notification to user",
            extra={"user_id": user_id},
            exc_info=exc,
        )


async def _process_single_messaging_event(
    event: dict[str, Any],
    verification_service: InstagramVerificationService,
    config: AppConfig,
) -> bool:
    """Process one messaging event. Returns True if processed."""
    is_echo = event.get("is_echo", False)
    is_self = event.get("is_self", False)
    if is_echo or is_self:
        return False

    sender = event.get("sender", {})
    sender_id = sender.get("id")
    if not sender_id:
        return False

    message = event.get("message", {})
    if not message:
        return False

    text = message.get("text", "").strip()
    if not text:
        return False

    try:
        verify = verification_service.verify_code_by_instagram_sender
        user_id = await verify(
            instagram_sender_id=sender_id,
            code=text,
            admin_instagram_username=config.instagram.admin_instagram_username,
        )
        if user_id:
            await _notify_user_verification_success(
                user_id, verification_service, config
            )
    except Exception as exc:
        logger.warning(
            "Error verifying code from Instagram webhook",
            extra={"sender_id": sender_id, "error": str(exc)},
            exc_info=exc,
        )
    return True


async def _process_webhook_events(
    payload: dict[str, Any],
    verification_service: InstagramVerificationService,
    config: AppConfig,
) -> None:
    """Process webhook events from Instagram.

    According to Instagram Webhooks documentation:
    https://developers.facebook.com/docs/instagram-platform/webhooks

    Payload structure for messages:
    {
      "object": "instagram",
      "entry": [
        {
          "id": "<PAGE_ID>",
          "time": 1234567890,
          "messaging": [
            {
              "sender": {"id": "<INSTAGRAM_USER_ID>"},
              "recipient": {"id": "<PAGE_ID>"},
              "timestamp": 1234567890,
              "message": {
                "mid": "<MESSAGE_ID>",
                "text": "ABC123XY"
              },
              "is_echo": false,  # True if message sent via API
              "is_self": false   # True if message from page to itself
            }
          ]
        }
      ]
    }
    """
    if payload.get("object") != "instagram":
        logger.debug(
            "Ignoring non-Instagram webhook event",
            extra={"object": payload.get("object")},
        )
        return

    entries = payload.get("entry", [])
    if not entries:
        logger.debug("No entries in webhook payload")
        return

    for entry in entries:
        page_id = entry.get("id")

        # Process messaging events (messages field)
        messaging = entry.get("messaging", [])
        if not messaging:
            logger.debug(
                "No messaging events in entry", extra={"page_id": page_id}
            )
            continue

        for event in messaging:
            await _process_single_messaging_event(
                event, verification_service, config
            )


def main() -> None:
    """Run the webhook server."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    log_startup_info(
        logger=logger, service_name="instagram-webhook", config=config
    )

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)


if __name__ == "__main__":
    main()
