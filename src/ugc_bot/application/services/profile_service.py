"""Service for building user profile summaries."""

from dataclasses import dataclass

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    UserRepository,
)
from uuid import UUID

from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import MessengerType


@dataclass(slots=True)
class ProfileService:
    """Build user profile summaries from repositories."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    advertiser_repo: AdvertiserProfileRepository

    async def get_user_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> User | None:
        """Fetch user by external id."""

        return await self.user_repo.get_by_external(external_id, messenger_type)

    async def get_blogger_profile(self, user_id: UUID) -> BloggerProfile | None:
        """Fetch blogger profile by user id."""

        return await self.blogger_repo.get_by_user_id(user_id)

    async def get_advertiser_profile(self, user_id: UUID) -> AdvertiserProfile | None:
        """Fetch advertiser profile by user id."""

        return await self.advertiser_repo.get_by_user_id(user_id)
