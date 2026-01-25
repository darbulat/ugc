"""Service for building user profile summaries."""

from dataclasses import dataclass

from ugc_bot.application.ports import UserRepository
from uuid import UUID

from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole


@dataclass(slots=True)
class ProfileService:
    """Build user profile summaries from repositories."""

    user_repo: UserRepository

    def get_user_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> User | None:
        """Fetch user by external id."""

        return self.user_repo.get_by_external(external_id, messenger_type)

    def get_blogger_profile(self, user_id: UUID) -> User | None:
        """Fetch blogger profile by user id."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            return None
        if user.role in {UserRole.BLOGGER, UserRole.BOTH} and user.instagram_url:
            return user
        return None

    def get_advertiser_profile(self, user_id: UUID) -> User | None:
        """Fetch advertiser profile by user id."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            return None
        if user.role in {UserRole.ADVERTISER, UserRole.BOTH} and user.contact:
            return user
        return None
