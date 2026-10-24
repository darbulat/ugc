"""Durable trusted receipt processing, independent of new-sales gates."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.checkout_ports import PaidReceiptRepository
from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.messenger.dto import PaymentSuccess
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.checkout import NativePaidReceipt


@dataclass
class PaidReceiptProcessor:
    repository: PaidReceiptRepository
    transactions: TransactionManager
    payments: PaymentService

    async def accept(self, receipt: NativePaidReceipt) -> bool:
        async with self.transactions.transaction() as session:
            return await self.repository.accept_receipt(
                receipt, session=session
            )

    async def run_once(self) -> bool:
        async with self.transactions.transaction() as session:
            claim = await self.repository.claim_receipt(session=session)
        if claim is None:
            return False
        receipt = claim["receipt"]
        outcome, error = "captured", None
        try:
            if claim["client_id"] is None:
                raise UserNotFoundError("trusted_payer_unresolved")
            await self.payments.confirm_telegram_payment(
                claim["client_id"],
                receipt.order_id,
                receipt.provider_charge_id,
                receipt.amount_minor,
                receipt.currency,
                PaymentSuccess(
                    str(receipt.order_id),
                    receipt.provider_charge_id,
                    receipt.amount_minor,
                    receipt.currency,
                    receipt.protocol_message_at,
                    receipt.telegram_charge_id,
                ),
            )
        except (
            OrderCreationError,
            UserNotFoundError,
            PermissionError,
            ValueError,
        ) as exc:
            outcome, error = "unresolved", type(exc).__name__
        # Transient SQL/transport failure retains the claimed lease. Capture
        # replay is idempotent after recovery, including uncertain commits.
        async with self.transactions.transaction() as session:
            await self.repository.finish_receipt(
                claim, outcome, error=error, session=session
            )
        return True


def native_receipt(incoming) -> NativePaidReceipt:
    paid = incoming.successful_payment
    if paid is None or paid.protocol_message_at is None:
        raise ValueError("trusted_native_receipt_required")
    return NativePaidReceipt(
        incoming.user.external_id,
        incoming.chat_id,
        incoming.message_id or "",
        UUID(paid.invoice_payload),
        paid.provider_payment_charge_id,
        paid.telegram_payment_charge_id or "",
        paid.total_amount,
        paid.currency,
        paid.protocol_message_at,
    )
