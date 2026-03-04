"""Context helpers for messenger-neutral handlers."""

from dataclasses import dataclass
from typing import Any

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.application.messenger.ports import MessengerClient


@dataclass(frozen=True, slots=True)
class UserContext:
    """Minimal user context for handler compatibility."""

    id: str
    username: str | None


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Minimal chat context for handler compatibility."""

    id: str


@dataclass(frozen=True, slots=True)
class PhotoContext:
    """Minimal photo context for handler compatibility."""

    file_id: str


class MessageContext:
    """Message adapter with an aiogram-like interface."""

    def __init__(
        self, incoming: IncomingMessage, messenger_client: MessengerClient
    ) -> None:
        """Initialize from IncomingMessage and MessengerClient."""
        self._incoming = incoming
        self._messenger_client = messenger_client
        self.bot = None
        self.from_user = UserContext(
            id=incoming.user.external_id,
            username=incoming.user.username,
        )
        self.chat = ChatContext(id=incoming.chat_id)
        self.photo = [
            PhotoContext(file_id=pid) for pid in incoming.photo_file_ids
        ]
        self.text = incoming.text
        self.contact_phone = getattr(incoming, "contact_phone", None)
        self.location_lat = getattr(incoming, "location_lat", None)
        self.location_lon = getattr(incoming, "location_lon", None)

    async def answer(
        self,
        text: str,
        *,
        reply_markup: Any | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
    ) -> None:
        """Send a reply message."""
        await self._messenger_client.send_text(
            chat_id=self._incoming.chat_id,
            text=text,
            keyboard=reply_markup,
            parse_mode=parse_mode,
            disable_preview=disable_web_page_preview,
        )

    async def edit_text(
        self,
        text: str,
        *,
        reply_markup: Any | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Edit the message text."""
        if not self._incoming.message_id:
            return
        await self._messenger_client.edit_text(
            chat_id=self._incoming.chat_id,
            message_id=self._incoming.message_id,
            text=text,
            keyboard=reply_markup,
            parse_mode=parse_mode,
        )

    async def edit_reply_markup(
        self, *, reply_markup: Any | None = None
    ) -> None:
        """Edit the message keyboard."""
        if not self._incoming.message_id:
            return
        await self._messenger_client.edit_reply_markup(
            chat_id=self._incoming.chat_id,
            message_id=self._incoming.message_id,
            keyboard=reply_markup,
        )


class CallbackContext:
    """Callback adapter with aiogram-like interface."""

    def __init__(
        self, incoming: IncomingCallback, messenger_client: MessengerClient
    ) -> None:
        """Initialize from IncomingCallback and MessengerClient."""
        self._incoming = incoming
        self._messenger_client = messenger_client
        self.bot = None
        self.from_user = UserContext(
            id=incoming.user.external_id,
            username=incoming.user.username,
        )
        self.data = incoming.data
        self.message = MessageContext(
            IncomingMessage(
                chat_id=incoming.chat_id,
                user=incoming.user,
                text=None,
                message_id=incoming.message_id,
            ),
            messenger_client,
        )

    async def answer(
        self, text: str | None = None, *, show_alert: bool = False
    ) -> None:
        """Answer callback query."""
        await self._messenger_client.answer_callback(
            callback_id=self._incoming.callback_id,
            text=text,
            show_alert=show_alert,
        )
