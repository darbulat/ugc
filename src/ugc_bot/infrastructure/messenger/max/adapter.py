"""MaxEventAdapter — converts raw Max webhook payloads to neutral DTOs."""

import re

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingPreCheckout,
    IncomingUser,
)
from ugc_bot.application.messenger.ports import MessengerEventAdapter
from ugc_bot.domain.enums import MessengerType

_VCF_TEL_RE = re.compile(r"TEL[^:]*:\s*([+\d\s()\-]+)")


def _extract_phone_from_vcf(vcf_info: str | None) -> str | None:
    """Extract phone number from a VCF/vCard string."""
    if not vcf_info:
        return None
    m = _VCF_TEL_RE.search(vcf_info)
    return m.group(1).strip() if m else None


def _extract_contact_phone(attachments: list[dict]) -> str | None:
    """Extract phone from ContactAttachment in message attachments."""
    for att in attachments:
        if att.get("type") == "contact":
            payload = att.get("payload") or {}
            return _extract_phone_from_vcf(payload.get("vcf_info"))
    return None


def _extract_location(
    attachments: list[dict],
) -> tuple[float | None, float | None]:
    """Extract lat/lon from LocationAttachment in message attachments."""
    for att in attachments:
        if att.get("type") == "location":
            lat = att.get("latitude")
            lon = att.get("longitude")
            if lat is not None and lon is not None:
                return float(lat), float(lon)
    return None, None


class MaxEventAdapter(MessengerEventAdapter):
    """Converts raw Max webhook event dicts to messenger-neutral DTOs."""

    def from_message(self, message: object) -> IncomingMessage:
        """Convert a message_created event to IncomingMessage."""
        event: dict = message  # type: ignore[assignment]
        msg = event["message"]
        sender = msg["sender"]
        recipient = msg["recipient"]
        body = msg.get("body", {})
        chat_id = str(recipient["chat_id"])

        user = IncomingUser(
            external_id=str(sender["user_id"]),
            messenger_type=MessengerType.MAX,
            username=sender.get("username"),
        )

        attachments: list[dict] = body.get("attachments") or []
        contact_phone = _extract_contact_phone(attachments)
        location_lat, location_lon = _extract_location(attachments)

        return IncomingMessage(
            chat_id=chat_id,
            user=user,
            text=body.get("text"),
            message_id=body.get("mid"),
            contact_phone=contact_phone,
            location_lat=location_lat,
            location_lon=location_lon,
            raw=event,
        )

    def from_callback(self, callback: object) -> IncomingCallback:
        """Convert a message_callback event to IncomingCallback."""
        event: dict = callback  # type: ignore[assignment]
        cb = event["callback"]
        cb_user = cb["user"]
        # "message" is a top-level field in the event, not nested in "callback"
        message = event["message"]
        recipient = message["recipient"]
        body = message.get("body", {})
        chat_id = str(recipient["chat_id"])

        user = IncomingUser(
            external_id=str(cb_user["user_id"]),
            messenger_type=MessengerType.MAX,
            username=cb_user.get("username"),
        )

        return IncomingCallback(
            callback_id=str(cb["callback_id"]),
            chat_id=chat_id,
            user=user,
            data=cb.get("payload"),
            message_id=body.get("mid"),
            message_text=body.get("text"),
            raw=event,
        )

    def from_bot_started(self, event: object) -> IncomingMessage:
        """Convert a bot_started event to IncomingMessage (like /start)."""
        data: dict = event  # type: ignore[assignment]
        user_data = data["user"]
        chat_id = str(data["chat_id"])

        user = IncomingUser(
            external_id=str(user_data["user_id"]),
            messenger_type=MessengerType.MAX,
            username=user_data.get("username"),
        )

        return IncomingMessage(
            chat_id=chat_id,
            user=user,
            text="/start",
            message_id=None,
            raw=data,
        )

    def from_pre_checkout(self, query: object) -> IncomingPreCheckout:
        """Max does not support payments."""
        raise NotImplementedError(
            "Max messenger does not support payments. "
            "Check messenger_type before calling from_pre_checkout."
        )
