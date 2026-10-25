"""Paid campaign access; usage is derived from real submissions and attempts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from ugc_bot.application.services.subscription_service import state
from ugc_bot.application.subscription_ports import SubscriptionRepository


class CampaignSubscriptionUsage(Protocol):
    async def usage(
        self, owner_id: UUID, starts_at: datetime, *, session: object
    ) -> tuple[int, int]: ...


@dataclass
class SubscriptionCampaignAccess:
    subscriptions: SubscriptionRepository
    campaigns: CampaignSubscriptionUsage

    async def require_access(
        self,
        owner_id: UUID,
        *,
        action: Literal["submit", "send"],
        at: datetime,
        session: object,
    ) -> None:
        # Caller has already locked the authoritative campaign users and scope.
        # Never acquire a later User lock or create a parallel usage counter.
        await self.subscriptions.lock(session=session)
        events = await self.subscriptions.events(session=session)
        if not any(e["action"] == "enable_automation" for e in events):
            raise PermissionError("campaign_subscription_required")
        current = state(events, owner_id, at)
        if current["state"] != "active":
            raise PermissionError("campaign_subscription_required")
        submissions, attempts = await self.campaigns.usage(
            owner_id,
            datetime.fromisoformat(current["starts_at"]),
            session=session,
        )
        used, limit = (
            (submissions, current["campaign_limit"])
            if action == "submit"
            else (attempts, current["recipient_limit"])
        )
        if used >= limit:
            raise PermissionError("campaign_subscription_quota_exceeded")
