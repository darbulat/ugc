"""Service for advertiser registration."""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import AdvertiserProfileRepository, UserRepository
from ugc_bot.domain.entities import AdvertiserProfile


@dataclass(slots=True)
class AdvertiserRegistrationService:
    """Register advertiser profiles with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    metrics_collector: Optional[Any] = None

    def register_advertiser(
        self, user_id: UUID, contact: str, instagram_url: str | None = None
    ) -> AdvertiserProfile:
        """Create an advertiser profile after validating input."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for advertiser registration.")

        contact = contact.strip()
        if not contact:
            raise AdvertiserRegistrationError("Contact is required.")

        profile = AdvertiserProfile(
            user_id=user.user_id,
            instagram_url=instagram_url,
            confirmed=False,
            contact=contact,
        )
        self.advertiser_repo.save(profile)

        if self.metrics_collector:
            self.metrics_collector.record_advertiser_registration(str(user.user_id))

        return profile

    def get_profile(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        return self.advertiser_repo.get_by_user_id(user_id)
