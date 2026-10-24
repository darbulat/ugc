"""A coherent own-client or own-assignment summary, without writes."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.campaign_summary_ports import CampaignSummaryRepository
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc


@dataclass
class CampaignSummaryService:
    repository: CampaignSummaryRepository
    transactions: TransactionManager
    clock: Clock

    async def view(
        self,
        order_id: UUID,
        actor_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        if principal is not None and (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        async with self.transactions.transaction() as session:
            await self.repository.begin_snapshot(session=session)
            result = await self.repository.view(
                order_id, actor_id, session=session, principal=principal
            )
            return dict(result, as_of=utc(self.clock.now()))
