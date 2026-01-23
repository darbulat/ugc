"""FastAPI application for Instagram webhook endpoint."""

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.config import AppConfig, load_config
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.instagram.graph_api_client import (
    HttpInstagramGraphApiClient,
)
from ugc_bot.logging_setup import configure_logging

logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Webhook")


def _get_services(config: AppConfig) -> InstagramVerificationService:
    """Create service instances for webhook processing."""
    session_factory = create_session_factory(config.database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    verification_repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=session_factory
    )

    # Create Instagram Graph API client if access token is configured
    instagram_api_client = None
    if config.instagram_access_token:
        instagram_api_client = HttpInstagramGraphApiClient(
            access_token=config.instagram_access_token,
            base_url=config.instagram_api_base_url,
        )

    return InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=verification_repo,
        instagram_api_client=instagram_api_client,
    )


def _verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Verify webhook signature using SHA256."""
    if not signature.startswith("sha256="):
        return False
    expected_signature = signature[7:]  # Remove "sha256=" prefix
    computed = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected_signature)


@app.get("/webhook/instagram")
async def verify_webhook(request: Request) -> Response:
    """Handle webhook verification request from Meta."""
    config = load_config()

    # FastAPI doesn't handle query params with dots well, so we use request.query_params
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")

    if hub_mode != "subscribe":
        logger.warning("Invalid hub.mode in verification request")
        raise HTTPException(status_code=400, detail="Invalid mode")

    if hub_verify_token != config.instagram_webhook_verify_token:
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
    if config.instagram_app_secret:
        if not x_hub_signature_256:
            logger.warning("Missing X-Hub-Signature-256 header")
            raise HTTPException(status_code=400, detail="Missing signature header")

        if not _verify_signature(
            payload_bytes, x_hub_signature_256, config.instagram_app_secret
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
        verification_service = _get_services(config)
        await _process_webhook_events(payload, verification_service, config)
    except Exception as exc:
        logger.exception("Error processing webhook events", exc_info=exc)
        # Still return 200 to prevent retries for processing errors
        return {"status": "error", "message": str(exc)}

    return {"status": "ok"}


def _notify_user_verification_success(user_id: UUID, config: AppConfig) -> None:
    """Send Telegram notification to user about successful verification."""
    try:
        from aiogram import Bot

        # Get user's Telegram external_id
        session_factory = create_session_factory(config.database_url)
        user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
        user = user_repo.get_by_id(user_id)
        if user is None:
            logger.warning(
                "User not found for verification notification",
                extra={"user_id": user_id},
            )
            return

        # Find Telegram user
        telegram_user = user_repo.get_by_external(
            external_id=user.external_id,
            messenger_type=MessengerType.TELEGRAM,
        )
        if telegram_user is None:
            logger.warning(
                "Telegram user not found for verification notification",
                extra={"user_id": user_id, "external_id": user.external_id},
            )
            return

        # Send message
        bot = Bot(token=config.bot_token)
        import asyncio

        async def send_notification() -> None:
            try:
                await bot.send_message(
                    chat_id=int(telegram_user.external_id),
                    text="✅ Instagram подтверждён. Теперь вы можете получать офферы.",
                )
            finally:
                await bot.session.close()

        asyncio.run(send_notification())
    except Exception as exc:
        logger.exception(
            "Error sending verification notification to user",
            extra={"user_id": user_id},
            exc_info=exc,
        )


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
            logger.debug("No messaging events in entry", extra={"page_id": page_id})
            continue

        for event in messaging:
            # Skip echo messages (messages sent via API)
            is_echo = event.get("is_echo", False)
            is_self = event.get("is_self", False)

            if is_echo or is_self:
                logger.debug(
                    "Skipping echo/self message",
                    extra={"is_echo": is_echo, "is_self": is_self},
                )
                continue

            sender = event.get("sender", {})
            sender_id = sender.get("id")
            if not sender_id:
                logger.debug("No sender ID in messaging event")
                continue

            recipient = event.get("recipient", {})
            recipient_id = recipient.get("id")

            message = event.get("message", {})
            if not message:
                logger.debug(
                    "No message object in event", extra={"sender_id": sender_id}
                )
                continue

            # Extract message text
            text = message.get("text", "").strip()
            if not text:
                logger.debug("Message has no text", extra={"sender_id": sender_id})
                continue

            message_id = message.get("mid")
            timestamp = event.get("timestamp")

            logger.info(
                "Processing Instagram message",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "text_preview": text[:20],
                },
            )

            # Verify code by Instagram sender ID
            # This will check if the code matches and the Instagram URL matches
            try:
                user_id = await verification_service.verify_code_by_instagram_sender(
                    instagram_sender_id=sender_id,
                    code=text,
                    admin_instagram_username=config.admin_instagram_username,
                )
                if user_id:
                    logger.info(
                        "Instagram verification successful via webhook",
                        extra={
                            "sender_id": sender_id,
                            "user_id": str(user_id),
                            "message_id": message_id,
                        },
                    )
                    # Send notification to user in Telegram
                    _notify_user_verification_success(user_id, config)
                else:
                    logger.debug(
                        "Instagram verification failed - code not found or expired",
                        extra={"sender_id": sender_id, "text_preview": text[:10]},
                    )
            except Exception as exc:
                logger.warning(
                    "Error verifying code from Instagram webhook",
                    extra={"sender_id": sender_id, "error": str(exc)},
                    exc_info=exc,
                )


def main() -> None:
    """Run the webhook server."""
    config = load_config()
    configure_logging(config.log_level, json_format=config.log_format.lower() == "json")

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)


if __name__ == "__main__":
    main()
