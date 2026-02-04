"""Service for NPS (Net Promoter Score) persistence."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.ports import NpsRepository, TransactionManager


@dataclass(slots=True)
class NpsService:
    """Handle NPS score persistence within transaction boundary."""

    nps_repo: NpsRepository
    transaction_manager: TransactionManager | None = None

    async def save(self, interaction_id: UUID, score: int) -> None:
        """Save NPS score for an interaction."""

        if self.transaction_manager is None:
            await self.nps_repo.save(interaction_id, score)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.nps_repo.save(interaction_id, score, session=session)
