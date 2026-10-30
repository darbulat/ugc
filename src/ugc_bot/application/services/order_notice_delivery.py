"""Persist each send attempt before delivery; retain ambiguous acceptance."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.application.order_notice_ports import (
    OrderNoticeJob,
    OrderNoticeRepository,
)
from ugc_bot.application.ports import TransactionManager

logger = logging.getLogger(__name__)


@dataclass
class OrderNoticeDelivery:
    repository: OrderNoticeRepository
    transactions: TransactionManager
    send: Callable[[OrderNoticeJob], Awaitable[None]]
    admin_recipients: Callable[[], Awaitable[tuple[str, ...]]]
    support_recipient: str = ""
    prepares_before_send: bool = False

    async def run_once(self) -> bool:
        addresses = await self.admin_recipients()
        async with self.transactions.transaction() as session:
            job = await self.repository.claim(
                datetime.now(timezone.utc),
                addresses,
                self.support_recipient,
                session=session,
            )
        if job is None:
            return False
        state, reason, retry_after = "sent", None, None
        try:
            if not self.prepares_before_send:
                async with self.transactions.transaction() as session:
                    started = await self.repository.begin(
                        job, datetime.now(timezone.utc), session=session
                    )
                if not started:
                    return False
            await self.send(job)
        except DeliveryFailure as exc:
            state = (
                "unknown"
                if exc.uncertain
                else ("pending" if job.attempt < 3 else "failed")
            )
            reason = exc.code
            retry_after = exc.retry_after_seconds
        except Exception:
            logger.exception(
                "Order notice acceptance is uncertain",
                extra={"job_id": str(job.job_id)},
            )
            state, reason = "unknown", "delivery_acceptance_unknown"
        async with self.transactions.transaction() as session:
            await self.repository.finish(
                job,
                state,
                reason,
                session=session,
                retry_after_seconds=retry_after,
            )
        return True
