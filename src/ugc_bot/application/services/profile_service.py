"""Service for building user profile summaries."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class ProfileService:
    """Build user profile summaries from repositories."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    advertiser_repo: AdvertiserProfileRepository
    transaction_manager: TransactionManager | None = None

    async def get_user_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> User | None:
        """Fetch user by external id."""

        async def _run(session: object | None):
            return await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_blogger_profile(self, user_id: UUID) -> BloggerProfile | None:
        """Fetch blogger profile by user id."""

        async def _run(session: object | None):
            return await self.blogger_repo.get_by_user_id(user_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_advertiser_profile(self, user_id: UUID) -> AdvertiserProfile | None:
        """Fetch advertiser profile by user id."""

        async def _run(session: object | None):
            return await self.advertiser_repo.get_by_user_id(user_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)
