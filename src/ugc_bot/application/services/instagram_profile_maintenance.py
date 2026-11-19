"""Observe only existing checks; drain a durable daytime notice queue."""

from datetime import datetime, timedelta

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.instagram_maintenance_ports import (
    InstagramMaintenanceRepository,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import (
    InstagramProfileInfo,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.instagram_maintenance import next_profile_notice_at


class InstagramProfileMaintenance:
    def __init__(
        self,
        repo: InstagramMaintenanceRepository,
        transactions: TransactionManager,
    ):
        self.repo, self.transactions = repo, transactions

    async def observe(
        self,
        profile: BloggerProfile,
        info: InstagramProfileInfo | None,
        at: datetime,
        *,
        error: str | None = None,
    ) -> bool:
        async with self.transactions.transaction() as session:
            return await self.repo.observe(
                profile,
                info,
                at,
                error=error,
                session=session,
            )

    async def verified(
        self,
        profile: BloggerProfile,
        at: datetime,
        *,
        previous_profile: BloggerProfile | None = None,
        session: object,
    ) -> None:
        await self.repo.verified(
            profile, at, previous_profile=previous_profile, session=session
        )


class InstagramProfileNoticeDelivery:
    def __init__(
        self,
        repo: InstagramMaintenanceRepository,
        transactions: TransactionManager,
        transport: NoticeReceiptTransport,
        clock: Clock,
    ):
        self.repo, self.transactions = repo, transactions
        self.transport, self.clock = transport, clock

    async def run_once(self, *, limit: int = 20) -> int:
        sent = 0
        for _ in range(limit):
            at = self.clock.now()
            if next_profile_notice_at(at) != at:
                break
            async with self.transactions.transaction() as session:
                notice = await self.repo.claim(at, session=session)
            if notice is None:
                break
            # A batch or a rate-limit delay may cross the closing boundary.
            at = self.clock.now()
            state, reference, reason, retry_at = "sent", None, None, None
            if next_profile_notice_at(at) != at:
                state, retry_at = "ready", next_profile_notice_at(at)
            else:
                try:
                    receipt = await self.transport.send(notice)
                    reference = receipt.reference
                    sent += 1
                except DeliveryFailure as exc:
                    state = "unknown" if exc.uncertain else "failed"
                    reason = exc.code
                    if (
                        not exc.uncertain
                        and exc.retry_after_seconds is not None
                    ):
                        state = "ready"
                        retry_at = next_profile_notice_at(
                            self.clock.now()
                            + timedelta(seconds=max(1, exc.retry_after_seconds))
                        )
                except Exception:
                    # The provider might have accepted before the disconnect.
                    state, reason = "unknown", "profile_notice_result_unknown"
            async with self.transactions.transaction() as session:
                await self.repo.finish(
                    notice,
                    state,
                    self.clock.now(),
                    reference=reference,
                    reason=reason,
                    retry_at=retry_at,
                    session=session,
                )
        return sent
