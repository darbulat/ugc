"""MaxEventAdapter — converts raw Max webhook payloads to neutral DTOs."""

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingPreCheckout,
    IncomingUser,
)
from ugc_bot.application.messenger.ports import MessengerEventAdapter
from ugc_bot.domain.enums import MessengerType


class MaxEventAdapter(MessengerEventAdapter):
    """Converts raw Max webhook event dicts to messenger-neutral DTOs."""

    def from_message(self, message: object) -> IncomingMessage:
        """Convert a message_created event to IncomingMessage."""
        event: dict = message  # type: ignore[assignment]
        msg = event["message"]
        sender = msg["sender"]
        recipient = msg["recipient"]
        body = msg.get("body", {})

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

    def from_callback(self, callback: object) -> IncomingCallback:
        """Convert a message_callback event to IncomingCallback."""
        event: dict = callback  # type: ignore[assignment]
        cb = event["callback"]
        cb_user = cb["user"]
        # "message" is a top-level field in the event, not nested in "callback"
        message = event.get("message", {})
        recipient = message.get("recipient", {})
        body = message.get("body", {})

        user = IncomingUser(
            external_id=str(cb_user["user_id"]),
            messenger_type=MessengerType.MAX,
            username=cb_user.get("username"),
        )

        return IncomingCallback(
            callback_id=str(cb["callback_id"]),
            chat_id=str(recipient.get("chat_id", "")),
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

        user = IncomingUser(
            external_id=str(user_data["user_id"]),
            messenger_type=MessengerType.MAX,
            username=user_data.get("username"),
        )

        return IncomingMessage(
            chat_id=str(data["chat_id"]),
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
