"""Service for blogger registration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender, WorkFormat


@dataclass(slots=True)
class BloggerRegistrationService:
    """Register blogger profiles with validation."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def get_profile_by_instagram_url(
        self, instagram_url: str
    ) -> BloggerProfile | None:
        """Fetch blogger profile by Instagram URL within a transaction boundary."""

        if self.transaction_manager is None:
            return await self.blogger_repo.get_by_instagram_url(instagram_url)
        async with self.transaction_manager.transaction() as session:
            return await self.blogger_repo.get_by_instagram_url(
                instagram_url, session=session
            )

    async def register_blogger(
        self,
        user_id: UUID,
        instagram_url: str,
        city: str,
        topics: dict[str, Any],
        audience_gender: AudienceGender,
        audience_age_min: int,
        audience_age_max: int,
        audience_geo: str,
        price: float,
        barter: bool,
        work_format: WorkFormat,
    ) -> BloggerProfile:
        """Create a blogger profile after validating input."""

        if self.transaction_manager is None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError("User not found for blogger registration.")

            instagram_url = instagram_url.strip()
            if not instagram_url:
                raise BloggerRegistrationError("Instagram URL is required.")

            existing_profile = await self.blogger_repo.get_by_instagram_url(
                instagram_url
            )
            if existing_profile is not None:
                raise BloggerRegistrationError(
                    "Этот Instagram аккаунт уже зарегистрирован. "
                    "Пожалуйста, используйте другой аккаунт."
                )

            city = city.strip()
            if not city:
                raise BloggerRegistrationError("City is required.")

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
                city=city,
                topics=topics,
                audience_gender=audience_gender,
                audience_age_min=audience_age_min,
                audience_age_max=audience_age_max,
                audience_geo=audience_geo,
                price=price,
                barter=barter,
                work_format=work_format,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(profile)

            if self.metrics_collector:
                self.metrics_collector.record_blogger_registration(str(user.user_id))

            return profile

        async with self.transaction_manager.transaction() as session:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError("User not found for blogger registration.")

            instagram_url = instagram_url.strip()
            if not instagram_url:
                raise BloggerRegistrationError("Instagram URL is required.")

            existing_profile = await self.blogger_repo.get_by_instagram_url(
                instagram_url, session=session
            )
            if existing_profile is not None:
                raise BloggerRegistrationError(
                    "Этот Instagram аккаунт уже зарегистрирован. "
                    "Пожалуйста, используйте другой аккаунт."
                )

            city = city.strip()
            if not city:
                raise BloggerRegistrationError("City is required.")

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
                city=city,
                topics=topics,
                audience_gender=audience_gender,
                audience_age_min=audience_age_min,
                audience_age_max=audience_age_max,
                audience_geo=audience_geo,
                price=price,
                barter=barter,
                work_format=work_format,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(profile, session=session)

            if self.metrics_collector:
                self.metrics_collector.record_blogger_registration(str(user.user_id))

            return profile

    async def update_blogger_profile(
        self,
        user_id: UUID,
        *,
        instagram_url: Optional[str] = None,
        city: Optional[str] = None,
        topics: Optional[dict[str, Any]] = None,
        audience_gender: Optional[AudienceGender] = None,
        audience_age_min: Optional[int] = None,
        audience_age_max: Optional[int] = None,
        audience_geo: Optional[str] = None,
        price: Optional[float] = None,
        barter: Optional[bool] = None,
        work_format: Optional[WorkFormat] = None,
    ) -> BloggerProfile | None:
        """Update blogger profile with provided fields. Returns updated profile or None if not found."""

        if self.transaction_manager is None:
            profile = await self.blogger_repo.get_by_user_id(user_id)
        else:
            async with self.transaction_manager.transaction() as session:
                profile = await self.blogger_repo.get_by_user_id(
                    user_id, session=session
                )
        if profile is None:
            return None

        updated = BloggerProfile(
            user_id=profile.user_id,
            instagram_url=instagram_url.strip()
            if instagram_url is not None
            else profile.instagram_url,
            confirmed=profile.confirmed,
            city=city.strip() if city is not None else profile.city,
            topics=topics if topics is not None else profile.topics,
            audience_gender=audience_gender
            if audience_gender is not None
            else profile.audience_gender,
            audience_age_min=audience_age_min
            if audience_age_min is not None
            else profile.audience_age_min,
            audience_age_max=audience_age_max
            if audience_age_max is not None
            else profile.audience_age_max,
            audience_geo=(
                audience_geo.strip()
                if audience_geo is not None
                else profile.audience_geo
            ),
            price=price if price is not None else profile.price,
            barter=barter if barter is not None else profile.barter,
            work_format=work_format if work_format is not None else profile.work_format,
            updated_at=datetime.now(timezone.utc),
        )

        if self.transaction_manager is None:
            await self.blogger_repo.save(updated)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.blogger_repo.save(updated, session=session)
        return updated
