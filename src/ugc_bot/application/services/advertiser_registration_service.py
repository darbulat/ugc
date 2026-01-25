"""Service for advertiser registration."""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import UserRole


@dataclass(slots=True)
class AdvertiserRegistrationService:
    """Register advertiser profiles with validation."""

    user_repo: UserRepository
    metrics_collector: Optional[Any] = None

    def register_advertiser(
        self, user_id: UUID, contact: str, instagram_url: str | None = None
    ) -> User:
        """Update user with advertiser fields after validating input."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for advertiser registration.")

        contact = contact.strip()
        if not contact:
            raise AdvertiserRegistrationError("Contact is required.")

        updated_role = _merge_roles(user.role, UserRole.ADVERTISER)
        updated_user = User(
            user_id=user.user_id,
            instagram_url=instagram_url,
            confirmed=False,
            contact=contact,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            role=updated_role,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            topics=user.topics,
            audience_gender=user.audience_gender,
            audience_age_min=user.audience_age_min,
            audience_age_max=user.audience_age_max,
            audience_geo=user.audience_geo,
            price=user.price,
            profile_updated_at=user.profile_updated_at,
        )
        self.user_repo.save(updated_user)

        if self.metrics_collector:
            self.metrics_collector.record_advertiser_registration(str(user.user_id))

        return updated_user

    def get_profile(self, user_id: UUID) -> Optional[User]:
        """Fetch advertiser data by user id."""

        user = self.user_repo.get_by_id(user_id)
        if user is None or user.contact is None:
            return None
        return user


def _merge_roles(existing: UserRole, incoming: UserRole) -> UserRole:
    """Merge role updates into a single user role."""

    if existing == incoming:
        return existing
    if existing == UserRole.BOTH or incoming == UserRole.BOTH:
        return UserRole.BOTH
    return UserRole.BOTH
