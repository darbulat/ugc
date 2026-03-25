"""MaxEventAdapter — converts raw Max webhook payloads to neutral DTOs."""

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.domain.enums import MessengerType


class MaxEventAdapter:
    """Converts raw Max webhook event dicts to messenger-neutral DTOs."""

    def from_message(self, event: dict) -> IncomingMessage:
        """Convert a message_created event to IncomingMessage."""
        message = event["message"]
        sender = message["sender"]
        recipient = message["recipient"]
        body = message.get("body", {})

        user = IncomingUser(
            external_id=str(sender["user_id"]),
            messenger_type=MessengerType.MAX,
            username=sender.get("username"),
        )

        return IncomingMessage(
            chat_id=str(recipient["chat_id"]),
            user=user,
            text=body.get("text"),
            message_id=body.get("mid"),
            raw=event,
        )

    def from_callback(self, event: dict) -> IncomingCallback:
        """Convert a message_callback event to IncomingCallback."""
        callback = event["callback"]
        cb_user = callback["user"]
        message = callback.get("message", {})
        recipient = message.get("recipient", {})
        body = message.get("body", {})

        user = IncomingUser(
            external_id=str(cb_user["user_id"]),
            messenger_type=MessengerType.MAX,
            username=cb_user.get("username"),
        )

        return IncomingCallback(
            callback_id=str(callback["callback_id"]),
            chat_id=str(recipient.get("chat_id", "")),
            user=user,
            data=callback.get("payload"),
            message_id=body.get("mid"),
            message_text=body.get("text"),
            raw=event,
        )
