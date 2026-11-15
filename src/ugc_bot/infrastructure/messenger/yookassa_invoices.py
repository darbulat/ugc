"""YooKassa invoice API with authenticated confirmation of captured payments."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx

from ugc_bot.domain.browser_checkout import (
    BrowserInvoice,
    BrowserPayment,
    InvoiceRejected,
    InvoiceUnavailable,
    browser_invoice_url,
)
from ugc_bot.domain.financial import utc


class YooKassaInvoices:
    def __init__(self, shop_id: str, secret: str, test_mode: bool):
        self.shop_id = shop_id
        self._secret = secret
        self.test_mode = test_mode

    async def observe(self, attempt) -> BrowserInvoice:
        try:
            async with httpx.AsyncClient(
                base_url="https://api.yookassa.ru/v3/",
                auth=(self.shop_id, self._secret),
                timeout=8.0,
            ) as client:
                invoice = await self._get_invoice(client, attempt)
                return await self._interpret(client, invoice, attempt)
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            ArithmeticError,
        ):
            raise InvoiceUnavailable("yookassa_invoice_unavailable") from None

    async def _get_invoice(self, client, attempt) -> dict:
        if attempt.invoice_id:
            invoice_id = attempt.invoice_id
            if invoice_id != f"in-{UUID(invoice_id.removeprefix('in-'))}":
                raise ValueError("invalid_invoice_id")
            response = await client.get(f"invoices/{invoice_id}")
        else:
            response = await client.post(
                "invoices",
                json=attempt.request,
                headers={"Idempotence-Key": str(attempt.attempt_id)},
            )
            if response.status_code == 400:
                error = response.json()
                if (
                    error.get("type") == "error"
                    and error.get("code") == "invalid_request"
                ):
                    raise InvoiceRejected("yookassa_rejected_invoice")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError("invalid_invoice")
        return value

    async def _interpret(self, client, invoice, attempt) -> BrowserInvoice:
        invoice_id = invoice["id"]
        if invoice_id != f"in-{UUID(invoice_id.removeprefix('in-'))}":
            raise ValueError("invalid_invoice_id")
        expected = {
            "order_id": str(attempt.order_id),
            "attempt_id": str(attempt.attempt_id),
        }
        if invoice["metadata"] != expected or attempt.invoice_id not in (
            None,
            invoice_id,
        ):
            raise ValueError("invoice_identity_mismatch")
        state = invoice["status"]
        if state == "canceled":
            return BrowserInvoice(invoice_id, state)
        if state == "pending":
            url = browser_invoice_url(invoice["delivery_method"]["url"])
            if (
                utc(datetime.fromisoformat(invoice["expires_at"]))
                != attempt.expires_at
            ):
                raise ValueError("invoice_expiry_mismatch")
            return BrowserInvoice(invoice_id, state, url)
        if state != "succeeded":
            raise ValueError("invoice_state_invalid")
        return await self._resolve_payment(client, invoice, attempt)

    async def _resolve_payment(
        self, client, invoice, attempt
    ) -> BrowserInvoice:
        invoice_id = invoice["id"]
        payment_id = str(UUID(invoice["payment_details"]["id"]))
        response = await client.get(f"payments/{payment_id}")
        response.raise_for_status()
        payment = response.json()
        if (
            payment["id"] != payment_id
            or payment["invoice_details"]["id"] != invoice_id
            or payment["recipient"]["account_id"] != self.shop_id
            or payment["test"] is not self.test_mode
            or payment["amount"]["currency"] != "RUB"
            or Decimal(payment["amount"]["value"]) * 100 != attempt.amount_minor
        ):
            raise ValueError("payment_identity_mismatch")
        if payment["status"] in {"pending", "waiting_for_capture", "canceled"}:
            # Release only on terminal cancellation of the whole invoice.
            return BrowserInvoice(invoice_id, "pending")
        if payment["status"] != "succeeded" or payment["paid"] is not True:
            raise ValueError("payment_not_captured")
        captured_at = utc(datetime.fromisoformat(payment["captured_at"]))
        if (
            not attempt.created_at
            <= captured_at
            <= datetime.now(captured_at.tzinfo)
        ):
            raise ValueError("payment_captured_time_invalid")
        return BrowserInvoice(
            invoice_id,
            "paid",
            payment=BrowserPayment(
                invoice_id,
                payment_id,
                self.shop_id,
                attempt.amount_minor,
                captured_at,
            ),
        )
