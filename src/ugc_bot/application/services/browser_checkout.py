"""Create and reconcile one YooKassa invoice per reserved order."""

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.domain.browser_checkout import InvoiceRejected, InvoiceUnavailable

logger = logging.getLogger(__name__)


class BrowserCheckoutService:
    def __init__(
        self, repository, transactions, gateway, receipt, *, can_create: bool
    ):
        self.repository = repository
        self.transactions = transactions
        self.gateway = gateway
        self.receipt = receipt
        self.can_create = can_create

    async def view(self, order_id: UUID):
        async with self.transactions.transaction() as session:
            return await self.repository.view(order_id, session=session)

    async def create(self, order_id: UUID, receipt_email: str):
        if not self.can_create:
            raise OrderCreationError("browser_payment_paused")
        email = receipt_email.strip()
        if len(email) > 254 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+", email
        ):
            raise OrderCreationError("browser_receipt_email_required")
        async with self.transactions.transaction() as session:
            await self.repository.reserve(
                order_id, email, self.receipt, session=session
            )
        await self.run_once(order_id)

    async def run_once(self, order_id: UUID | None = None) -> bool:
        async with self.transactions.transaction() as session:
            claim = await self.repository.claim(order_id, session=session)
        if claim is None:
            return False

        invoice, state = None, None
        try:
            if (
                claim.invoice_id is None
                and datetime.now(timezone.utc) >= claim.expires_at
            ):
                # No link left this system, and the immutable provider
                # request can only create an expired invoice.
                state = "failed"
            else:
                invoice = await self.gateway.observe(claim)
        except InvoiceRejected:
            state = "failed"
        except InvoiceUnavailable:
            logger.warning(
                "YooKassa invoice status unavailable",
                extra={"order_id": str(claim.order_id)},
            )
        try:
            async with self.transactions.transaction() as session:
                await self.repository.finish(
                    claim, invoice, state, session=session
                )
        except OrderCreationError:
            logger.error(
                "Verified browser payment requires reconciliation",
                extra={"order_id": str(claim.order_id)},
            )
            async with self.transactions.transaction() as session:
                review = (
                    replace(invoice, state="review", url=None, payment=None)
                    if invoice is not None
                    else None
                )
                await self.repository.finish(
                    claim, review, "review", session=session
                )
        return True
