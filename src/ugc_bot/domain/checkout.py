"""Native checkout facts; a client callback is never payment evidence."""

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class CheckoutActor:
    user_id: UUID
    platform: str
    external_id: str


@dataclass(frozen=True)
class PreparedInvoice:
    attempt_id: UUID
    order_id: UUID
    currency: str
    selection_minor: int
    accompaniment_minor: int
    description: str

    @property
    def total_minor(self) -> int:
        return self.selection_minor + self.accompaniment_minor


class LinkRejected(Exception):
    """A definite provider rejection, rather than an uncertain call result."""


@dataclass(frozen=True)
class NativePaidReceipt:
    payer_external_id: str
    chat_id: str
    message_id: str
    order_id: UUID
    provider_charge_id: str
    telegram_charge_id: str
    amount_minor: int
    currency: str
    protocol_message_at: datetime


def invoice_url(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"https://t\.me/(?:\$|invoice/)[A-Za-z0-9_-]{1,512}", value
    ):
        raise ValueError("invalid_invoice_url")
    return value
