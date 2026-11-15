"""The authenticated provider contract is the source of browser paid facts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from ugc_bot.domain.browser_checkout import InvoiceUnavailable
from ugc_bot.infrastructure.messenger.yookassa_invoices import YooKassaInvoices

INVOICE = f"in-{uuid4()}"
PAYMENT = str(uuid4())
URL = "https://yookassa.ru/my/i/synthetic/a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "create",
        "paid",
        "wrong_amount",
        "test_mismatch",
        "canceled",
        "invalid_url",
    ],
)
async def test_yookassa_invoice_contract(monkeypatch, case):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    attempt = SimpleNamespace(
        order_id=uuid4(),
        attempt_id=uuid4(),
        amount_minor=500000,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        invoice_id=None if case == "create" else INVOICE,
        request={"frozen": True},
    )
    metadata = {
        "order_id": str(attempt.order_id),
        "attempt_id": str(attempt.attempt_id),
    }

    def response(request):
        assert request.headers["authorization"] == "Basic MTIzOnNlY3JldA=="
        assert request.url.host == "api.yookassa.ru"
        if request.method == "POST":
            assert request.url.path == "/v3/invoices"
            assert request.headers["idempotence-key"] == str(attempt.attempt_id)
        if request.url.path.endswith(PAYMENT):
            return httpx.Response(
                200,
                json={
                    "id": PAYMENT,
                    "status": "succeeded",
                    "paid": True,
                    "invoice_details": {"id": INVOICE},
                    "recipient": {"account_id": "123"},
                    "test": case != "test_mismatch",
                    "amount": {
                        "value": "4999.00"
                        if case == "wrong_amount"
                        else "5000.00",
                        "currency": "RUB",
                    },
                    "captured_at": now.isoformat(),
                },
            )
        status = {
            "create": "pending",
            "invalid_url": "pending",
            "canceled": "canceled",
        }.get(case, "succeeded")
        return httpx.Response(
            200,
            json={
                "id": INVOICE,
                "metadata": metadata,
                "status": status,
                "payment_details": {"id": PAYMENT},
                "expires_at": attempt.expires_at.isoformat(),
                "delivery_method": {
                    "url": "https://example.org/invoice"
                    if case == "invalid_url"
                    else URL
                },
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(
            transport=httpx.MockTransport(response), **kwargs
        ),
    )
    gateway = YooKassaInvoices("123", "secret", True)
    if case in {"wrong_amount", "test_mismatch", "invalid_url"}:
        with pytest.raises(InvoiceUnavailable):
            await gateway.observe(attempt)
    else:
        result = await gateway.observe(attempt)
        assert result.invoice_id == INVOICE
        assert (
            result.state
            == {"create": "pending", "paid": "paid", "canceled": "canceled"}[
                case
            ]
        )
        if case == "paid":
            assert result.payment.payment_id == PAYMENT
            assert result.payment.amount_minor == 500000
        if case == "create":
            assert result.url == URL
