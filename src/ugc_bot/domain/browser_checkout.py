"""Facts read directly from the configured YooKassa merchant API."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

BROWSER_PAGE_PATH = "/miniapp/browser-payment.html"
CONSULTATION_PAYMENT_PATH = f"{BROWSER_PAGE_PATH}?service=consultation"

BROWSER_PROVIDER = "yookassa_browser"
BROWSER_CAPTURE_SOURCE = "yookassa.payment.captured_at"


@dataclass(frozen=True)
class BrowserPayment:
    invoice_id: str
    payment_id: str
    shop_id: str
    amount_minor: int
    captured_at: datetime


@dataclass(frozen=True)
class BrowserInvoice:
    invoice_id: str
    state: str
    url: str | None = None
    payment: BrowserPayment | None = None

    def __post_init__(self) -> None:
        if (self.state == "paid") != (self.payment is not None):
            raise ValueError("browser_capture_proof_required")


class InvoiceUnavailable(Exception):
    """A transport error or an unexpected provider response."""


class InvoiceRejected(Exception):
    """The provider explicitly rejected the create request."""


def browser_invoice_url(value: str) -> str:
    import re

    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.netloc != "yookassa.ru"
        or not re.fullmatch(
            r"/my/i/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", parts.path
        )
        or parts.fragment
        or parts.query
    ):
        raise ValueError("browser_invoice_url_invalid")
    return value
