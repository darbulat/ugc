"""Ports for messenger abstractions."""

from typing import Protocol

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingPreCheckout,
    Invoice,
    Keyboard,
)


class MessengerClient(Protocol):
    """Port for sending messages to a messenger."""

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        """Send a text message."""

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Send a photo message."""

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Edit message text."""

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        """Edit message keyboard (or remove)."""

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Answer a callback query."""

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        """Send invoice for payment."""


class MessengerEventAdapter(Protocol):
    """Port for adapting messenger events into DTOs."""

    def from_message(self, message: object) -> IncomingMessage:
        """Convert a messenger message into IncomingMessage."""

    def from_callback(self, callback: object) -> IncomingCallback:
        """Convert a messenger callback into IncomingCallback."""

    def from_pre_checkout(self, query: object) -> IncomingPreCheckout:
        """Convert a pre-checkout query into IncomingPreCheckout."""


class PaymentProvider(Protocol):
    """Port for messenger-specific payment operations."""

    async def confirm_pre_checkout(self, *, query_id: str) -> None:
        """Confirm pre-checkout query."""

    async def reject_pre_checkout(
        self, *, query_id: str, error_message: str
    ) -> None:
        """Reject pre-checkout query with error message."""
