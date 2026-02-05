"""Service for NPS (Net Promoter Score) persistence."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import NpsRepository, TransactionManager


@dataclass(slots=True)
class NpsService:
    """Handle NPS score persistence within transaction boundary."""

    nps_repo: NpsRepository
    transaction_manager: TransactionManager | None = None

    async def save(
        self,
        user_id: UUID,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> None:
        """Save NPS score for a user."""

        if session is not None:
            await self.nps_repo.save(user_id, score, comment, session=session)
        elif self.transaction_manager is None:
            await self.nps_repo.save(user_id, score, comment)
        else:
            async with self.transaction_manager.transaction() as tx_session:
                await self.nps_repo.save(user_id, score, comment, session=tx_session)

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""

        if session is not None:
            return await self.nps_repo.exists_for_user(user_id, session=session)
        if self.transaction_manager is None:
            return await self.nps_repo.exists_for_user(user_id)
        async with self.transaction_manager.transaction() as tx_session:
            return await self.nps_repo.exists_for_user(user_id, session=tx_session)
