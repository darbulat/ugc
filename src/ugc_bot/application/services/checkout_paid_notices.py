"""Operational paid notices: durable attempt, unlocked send, durable proof."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.checkout_ports import PaidNoticeRepository
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import TransactionManager


@dataclass(frozen=True)
class PaidNotice:
    attempt_id: UUID
    job_id: UUID
    channel: str
    address: str
    text: str
    address_kind: str = "chat_id"
    action_url: str | None = None
    action_label: str | None = None


@dataclass
class PaidNoticeDelivery:
    repository: PaidNoticeRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport

    async def run_once(self) -> bool:
        async with self.transactions.transaction() as session:
            notice = await self.repository.claim_notice(session=session)
        if notice is None:
            return False
        outcome, reference = "unknown", None
        try:
            receipt = await self.transport.send(notice)
            if receipt.channel != notice.channel or not receipt.reference:
                raise ValueError("paid_notice_receipt_mismatch")
            outcome, reference = "accepted", receipt.reference
        except DeliveryFailure as exc:
            outcome = "unknown" if exc.uncertain else "failed"
        except Exception:
            outcome = "unknown"
        async with self.transactions.transaction() as session:
            await self.repository.finish_notice(
                notice, outcome, reference, session=session
            )
        return True
