"""DTO models for messenger-neutral interactions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ugc_bot.domain.enums import MessengerType


class KeyboardKind(StrEnum):
    """Supported keyboard kinds."""

    INLINE = "inline"
    REPLY = "reply"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class Button:
    """Neutral button representation."""

    text: str
    callback_data: str | None = None
    url: str | None = None
    request_contact: bool = False
    request_location: bool = False
    web_app_url: str | None = None


@dataclass(frozen=True, slots=True)
class Keyboard:
    """Neutral keyboard representation."""

    kind: KeyboardKind
    rows: list[list[Button]] = field(default_factory=list)
    one_time: bool | None = None
    resize: bool | None = None
    is_persistent: bool | None = None

    @property
    def keyboard(self) -> list[list[Button]]:
        """Alias for rows (test compatibility)."""
        return self.rows


@dataclass(frozen=True, slots=True)
class Attachment:
    """Neutral media attachment representation."""

    file_id: str
    media_type: str = "photo"


@dataclass(frozen=True, slots=True)
class IncomingUser:
    """Incoming user information."""

    external_id: str
    messenger_type: MessengerType
    username: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentSuccess:
    """Successful payment payload information."""

    invoice_payload: str
    provider_payment_charge_id: str
    total_amount: int
    currency: str
    # Authenticated Telegram message time, NOT bank settlement time.
    protocol_message_at: datetime | None = None
    telegram_payment_charge_id: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """Incoming message DTO."""

    chat_id: str
    user: IncomingUser
    text: str | None = None
    message_id: str | None = None
    photo_file_ids: list[str] = field(default_factory=list)
    successful_payment: PaymentSuccess | None = None
    contact_phone: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None
    web_app_data: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class IncomingCallback:
    """Incoming callback DTO."""

    callback_id: str
    chat_id: str
    user: IncomingUser
    data: str | None = None
    message_id: str | None = None
    message_text: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class IncomingPreCheckout:
    """Incoming pre-checkout query DTO."""

    query_id: str
    user: IncomingUser
    payload: str
    total_amount: int | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceItem:
    """Invoice line item."""

    label: str
    amount_minor: int


@dataclass(frozen=True, slots=True)
class Invoice:
    """Neutral invoice model."""

    title: str
    description: str
    payload: str
    provider_token: str
    currency: str
    items: list[InvoiceItem]
    provider_data: str | None = None
    need_email: bool = False
    send_email_to_provider: bool = False
    pay_button_text: str | None = None
