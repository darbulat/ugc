"""Explicit recipient interest and aggregate own-campaign reports."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ugc_bot.application.financial_ports import Clock
from ugc_bot.domain.campaigns import digest
from ugc_bot.domain.financial import utc


@dataclass
class CampaignResponseService:
    repository: Any
    clock: Clock

    async def view(
        self, actor_id: UUID, campaign_id: UUID, *, principal, session
    ):
        return await self.repository.recipient_view(
            actor_id,
            campaign_id,
            principal=principal,
            at=utc(self.clock.now()),
            session=session,
        )

    async def respond(
        self,
        actor_id: UUID,
        campaign_id: UUID,
        operation_key: str,
        expected_version: int,
        choice: str,
        *,
        principal,
        session,
    ):
        if (
            not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key) > 256
            or type(expected_version) is not int
            or expected_version < 0
            or choice not in ("interested", "declined", "withdrawn")
        ):
            raise ValueError("campaign_request_invalid")
        payload_hash = digest(
            {
                "campaign_id": str(campaign_id),
                "choice": choice,
                "expected_version": expected_version,
            }
        )
        return await self.repository.respond(
            actor_id,
            campaign_id,
            operation_key,
            expected_version,
            choice,
            payload_hash,
            principal=principal,
            at=utc(self.clock.now()),
            session=session,
        )

    async def report(
        self, actor_id: UUID, campaign_id: UUID, *, principal, session
    ):
        return await self.repository.report(
            actor_id,
            campaign_id,
            principal=principal,
            at=utc(self.clock.now()),
            session=session,
        )
