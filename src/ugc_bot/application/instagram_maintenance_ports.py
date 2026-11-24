"""Narrow profile-observation and delivery boundaries."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.notice_delivery_ports import ReceiptCard
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.domain.entities import BloggerProfile


@dataclass(frozen=True, slots=True)
class ProfileNotice:
    job_id: UUID
    lease: UUID
    channel: str
    address: str
    address_kind: str
    text: str
    card: ReceiptCard
    action_url: str | None = None
    action_label: str | None = None


class InstagramMaintenanceRepository(Protocol):
    async def claim_offer_checks(
        self,
        at: datetime,
        limit: int,
        *,
        session: object,
        order_id: UUID | None = None,
        creator_id: UUID | None = None,
    ) -> list[BloggerProfile]: ...

    async def contact_under_review(
        self, order_id: UUID, creator_id: UUID, *, session: object
    ) -> bool: ...

    async def recent_provider_success(
        self, since: datetime, *, session: object
    ) -> bool: ...

    async def observe(
        self,
        profile: BloggerProfile,
        info: InstagramProfileInfo | None,
        at: datetime,
        *,
        error: str | None,
        session: object,
    ) -> bool: ...

    async def verified(
        self,
        profile: BloggerProfile,
        at: datetime,
        *,
        previous_profile: BloggerProfile | None = None,
        session: object,
    ) -> None: ...

    async def claim(
        self,
        at: datetime,
        *,
        session: object,
    ) -> ProfileNotice | None: ...

    async def finish(
        self,
        notice: ProfileNotice,
        state: str,
        at: datetime,
        *,
        reference: str | None = None,
        reason: str | None = None,
        retry_at: datetime | None = None,
        session: object,
    ) -> None: ...
