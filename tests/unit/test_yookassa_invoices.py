"""The authenticated provider contract is the source of browser paid facts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from ugc_bot.domain.browser_checkout import (
    BrowserInvoice,
    InvoiceRejected,
    InvoiceUnavailable,
)
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
        "rejected",
        "invalid_payload",
        "invalid_id",
        "invalid_returned_id",
        "foreign_invoice",
        "invalid_expiry",
        "invalid_invoice_state",
        "waiting",
        "unpaid",
        "old_capture",
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
        invoice_id={
            "create": None,
            "rejected": None,
            "invalid_id": str(uuid4()),
        }.get(case, INVOICE),
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
            if case == "rejected":
                return httpx.Response(
                    400, json={"type": "error", "code": "invalid_request"}
                )
        if case == "invalid_payload":
            return httpx.Response(200, json=[])
        if request.url.path.endswith(PAYMENT):
            return httpx.Response(
                200,
                json={
                    "id": PAYMENT,
                    "status": "waiting_for_capture"
                    if case == "waiting"
                    else "succeeded",
                    "paid": case != "unpaid",
                    "invoice_details": {"id": INVOICE},
                    "recipient": {"account_id": "123"},
                    "test": case != "test_mismatch",
                    "amount": {
                        "value": "4999.00"
                        if case == "wrong_amount"
                        else "5000.00",
                        "currency": "RUB",
                    },
                    "captured_at": (now - timedelta(seconds=1)).isoformat()
                    if case == "old_capture"
                    else now.isoformat(),
                },
            )
        status = {
            "create": "pending",
            "invalid_url": "pending",
            "canceled": "canceled",
            "invalid_expiry": "pending",
            "invalid_invoice_state": "unknown",
        }.get(case, "succeeded")
        return httpx.Response(
            200,
            json={
                "id": PAYMENT if case == "invalid_returned_id" else INVOICE,
                "metadata": {} if case == "foreign_invoice" else metadata,
                "status": status,
                "payment_details": {"id": PAYMENT},
                "expires_at": now.isoformat()
                if case == "invalid_expiry"
                else attempt.expires_at.isoformat(),
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
    expected_states = {
        "create": "pending",
        "paid": "paid",
        "canceled": "canceled",
        "waiting": "pending",
    }
    if case == "rejected":
        with pytest.raises(InvoiceRejected):
            await gateway.observe(attempt)
    elif case not in expected_states:
        with pytest.raises(InvoiceUnavailable):
            await gateway.observe(attempt)
    else:
        result = await gateway.observe(attempt)
        assert result.invoice_id == INVOICE
        assert result.state == expected_states[case]
        if case == "paid":
            assert result.payment.payment_id == PAYMENT
            assert result.payment.amount_minor == 500000
        if case == "create":
            assert result.url == URL


def test_paid_invoice_requires_payment_evidence():
    with pytest.raises(ValueError, match="browser_capture_proof_required"):
        BrowserInvoice(INVOICE, "paid")
