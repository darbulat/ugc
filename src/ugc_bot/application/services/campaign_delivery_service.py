"""Commit one attempt before I/O. Uncertain or crashed sends never retry."""

from dataclasses import dataclass

from ugc_bot.application.campaign_runtime_ports import (
    CampaignAccess,
    CampaignDeliveryRepository,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc


@dataclass
class CampaignDeliveryService:
    repository: CampaignDeliveryRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    clock: Clock
    enabled: bool = False
    access: CampaignAccess | None = None

    async def run_once(self, *, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("campaign_worker_bounds_invalid")
        if not self.enabled:
            return 0
        async with self.transactions.transaction() as session:
            jobs = await self.repository.pending(
                utc(self.clock.now()), limit, session=session
            )
        sent = 0
        for job in jobs:
            async with self.transactions.transaction() as session:
                attempt = await self.repository.prepare(
                    job,
                    utc(self.clock.now()),
                    access=self.access,
                    session=session,
                )
            if attempt is None:
                continue
            status, reference, reason = "unknown", None, None
            try:
                receipt = await self.transport.send(attempt)
                if (
                    not isinstance(receipt, DeliveryReceipt)
                    or receipt.channel != "telegram"
                    or not receipt.reference.strip()
                ):
                    raise DeliveryFailure(
                        "campaign_receipt_unknown", uncertain=True
                    )
                status, reference = "accepted", receipt.reference
            except DeliveryFailure as error:
                status = "unknown" if error.uncertain else "failed"
                reason = "campaign_delivery_" + status
            except Exception:
                reason = "campaign_delivery_unknown"
            async with self.transactions.transaction() as session:
                await self.repository.finish(
                    attempt,
                    status,
                    reference,
                    reason,
                    utc(self.clock.now()),
                    session=session,
                )
            sent += 1
        return sent
