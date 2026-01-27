"""Service for blogger registration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.ports import BloggerProfileRepository, UserRepository
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender


@dataclass(slots=True)
class BloggerRegistrationService:
    """Register blogger profiles with validation."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    metrics_collector: Optional[Any] = None

    async def register_blogger(
        self,
        user_id: UUID,
        instagram_url: str,
        topics: dict[str, Any],
        audience_gender: AudienceGender,
        audience_age_min: int,
        audience_age_max: int,
        audience_geo: str,
        price: float,
    ) -> BloggerProfile:
        """Create a blogger profile after validating input."""

        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for blogger registration.")

        instagram_url = instagram_url.strip()
        if not instagram_url:
            raise BloggerRegistrationError("Instagram URL is required.")

        # Check if Instagram URL is already taken
        existing_profile = await self.blogger_repo.get_by_instagram_url(instagram_url)
        if existing_profile is not None:
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

        profile = BloggerProfile(
            user_id=user.user_id,
            instagram_url=instagram_url,
            confirmed=False,
            topics=topics,
            audience_gender=audience_gender,
            audience_age_min=audience_age_min,
            audience_age_max=audience_age_max,
            audience_geo=audience_geo,
            price=price,
            updated_at=datetime.now(timezone.utc),
        )
        await self.blogger_repo.save(profile)

        if self.metrics_collector:
            self.metrics_collector.record_blogger_registration(str(user.user_id))

        return profile
