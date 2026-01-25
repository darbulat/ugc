"""Service for blogger registration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import AudienceGender, UserRole


@dataclass(slots=True)
class BloggerRegistrationService:
    """Register blogger profiles with validation."""

    user_repo: UserRepository
    metrics_collector: Optional[Any] = None

    def register_blogger(
        self,
        user_id: UUID,
        instagram_url: str,
        topics: dict[str, Any],
        audience_gender: AudienceGender,
        audience_age_min: int,
        audience_age_max: int,
        audience_geo: str,
        price: float,
    ) -> User:
        """Update user with blogger profile fields after validating input."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for blogger registration.")

        instagram_url = instagram_url.strip()
        if not instagram_url:
            raise BloggerRegistrationError("Instagram URL is required.")

        # Check if Instagram URL is already taken
        existing_user = self.user_repo.get_by_instagram_url(instagram_url)
        if existing_user is not None and existing_user.user_id != user.user_id:
            raise BloggerRegistrationError(
                "Этот Instagram аккаунт уже зарегистрирован. "
                "Пожалуйста, используйте другой аккаунт."
            )

        audience_geo = audience_geo.strip()
        if not audience_geo:
            raise BloggerRegistrationError("Audience geo is required.")

        if audience_age_min <= 0 or audience_age_max <= 0:
            raise BloggerRegistrationError("Audience age must be positive.")
        if audience_age_max < audience_age_min:
            raise BloggerRegistrationError("Age max must be >= age min.")

        if price <= 0:
            raise BloggerRegistrationError("Price must be positive.")

        updated_role = _merge_roles(user.role, UserRole.BLOGGER)
        updated_user = User(
            user_id=user.user_id,
            instagram_url=instagram_url,
            confirmed=False,
            topics=topics,
            audience_gender=audience_gender,
            audience_age_min=audience_age_min,
            audience_age_max=audience_age_max,
            audience_geo=audience_geo,
            price=price,
            profile_updated_at=datetime.now(timezone.utc),
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            role=updated_role,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            contact=user.contact,
        )
        self.user_repo.save(updated_user)

        if self.metrics_collector:
            self.metrics_collector.record_blogger_registration(str(user.user_id))

        return updated_user


def _merge_roles(existing: UserRole, incoming: UserRole) -> UserRole:
    """Merge role updates into a single user role."""

    if existing == incoming:
        return existing
    if existing == UserRole.BOTH or incoming == UserRole.BOTH:
        return UserRole.BOTH
    return UserRole.BOTH
