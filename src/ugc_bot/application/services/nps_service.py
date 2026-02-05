"""Service for NPS (Net Promoter Score) persistence."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import NpsRepository, TransactionManager
from ugc_bot.infrastructure.db.session import with_optional_tx


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
            return

        async def _run(s: object | None):
            await self.nps_repo.save(user_id, score, comment, session=s)

        await with_optional_tx(self.transaction_manager, _run)

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""

        if session is not None:
            return await self.nps_repo.exists_for_user(user_id, session=session)

        async def _run(s: object | None):
            return await self.nps_repo.exists_for_user(user_id, session=s)

        return await with_optional_tx(self.transaction_manager, _run)
