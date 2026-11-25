"""Observe only existing checks; drain a durable daytime notice queue."""

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID

from ugc_bot.application.errors import (
    InstagramProfileUnavailableError,
    InstagramUserNotFoundError,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.instagram_maintenance_ports import (
    InstagramMaintenanceRepository,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import (
    InstagramGraphApiClient,
    InstagramProfileInfo,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.instagram_maintenance import next_profile_notice_at

logger = logging.getLogger(__name__)


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


class InstagramOfferContactCheck:
    """Refresh only verified creators with a confirmed, undelivered response."""

    def __init__(
        self,
        maintenance: InstagramProfileMaintenance,
        client: InstagramGraphApiClient,
        clock: Clock,
    ):
        self.maintenance, self.client, self.clock = maintenance, client, clock

    async def run_once(
        self, *, order_id: UUID | None = None, creator_id: UUID | None = None
    ) -> None:
        at = self.clock.now()
        async with self.maintenance.transactions.transaction() as session:
            targets = await self.maintenance.repo.claim_offer_checks(
                at,
                1 if creator_id else 5,
                session=session,
                order_id=order_id,
                creator_id=creator_id,
            )
        unavailable = []
        provider_responded = False
        for profile in targets:
            assert profile.instagram_user_id
            try:
                async with asyncio.timeout(5):
                    info = await self.client.get_profile_by_id(
                        profile.instagram_user_id
                    )
            except (
                InstagramProfileUnavailableError,
                InstagramUserNotFoundError,
            ) as exc:
                reason = (
                    "100/33"
                    if isinstance(exc, InstagramProfileUnavailableError)
                    else "not_found"
                )
                unavailable.append((profile, reason))
            except Exception as exc:
                logger.warning(
                    "Instagram offer check failed (%s)", type(exc).__name__
                )
            else:
                if info is not None and info.username:
                    provider_responded = True
                    await self.maintenance.observe(profile, info, at)
        # As in the regular collection batch, a provider outage must not
        # turn a whole cohort into unavailable creators.
        if unavailable and not provider_responded:
            async with self.maintenance.transactions.transaction() as session:
                provider_responded = (
                    await self.maintenance.repo.recent_provider_success(
                        at - timedelta(minutes=15), session=session
                    )
                )
        if provider_responded:
            for profile, reason in unavailable:
                await self.maintenance.observe(profile, None, at, error=reason)

    async def before_contact(self, order_id: UUID, creator_id: UUID) -> bool:
        await self.run_once(order_id=order_id, creator_id=creator_id)
        async with self.maintenance.transactions.transaction() as session:
            return not await self.maintenance.repo.contact_under_review(
                order_id, creator_id, session=session
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
