"""Service for building user profile summaries."""

from dataclasses import dataclass
from typing import Any, AsyncContextManager, Protocol

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    UserRepository,
)
from uuid import UUID

from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import MessengerType


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


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

        if self.transaction_manager is None:
            return await self.user_repo.get_by_external(external_id, messenger_type)
        async with self.transaction_manager.transaction() as session:
            return await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )

    async def get_blogger_profile(self, user_id: UUID) -> BloggerProfile | None:
        """Fetch blogger profile by user id."""

        if self.transaction_manager is None:
            return await self.blogger_repo.get_by_user_id(user_id)
        async with self.transaction_manager.transaction() as session:
            return await self.blogger_repo.get_by_user_id(user_id, session=session)

    async def get_advertiser_profile(self, user_id: UUID) -> AdvertiserProfile | None:
        """Fetch advertiser profile by user id."""

        if self.transaction_manager is None:
            return await self.advertiser_repo.get_by_user_id(user_id)
        async with self.transaction_manager.transaction() as session:
            return await self.advertiser_repo.get_by_user_id(user_id, session=session)
