"""Service for advertiser registration."""

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import AdvertiserProfile


@dataclass(slots=True)
class AdvertiserRegistrationService:
    """Register advertiser profiles with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def register_advertiser(
        self,
        user_id: UUID,
        phone: str,
        brand: str,
        site_link: Optional[str] = None,
    ) -> AdvertiserProfile:
        """Create an advertiser profile after validating input."""

        phone = phone.strip()
        brand = brand.strip()
        site_link = (site_link or "").strip() or None
        if not phone:
            raise AdvertiserRegistrationError("Phone is required.")
        if not brand:
            raise AdvertiserRegistrationError("Brand is required.")

        if self.transaction_manager is None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError("User not found for advertiser registration.")

            profile = AdvertiserProfile(
                user_id=user.user_id,
                phone=phone,
                brand=brand,
                site_link=site_link,
            )
            await self.advertiser_repo.save(profile)
        else:
            async with self.transaction_manager.transaction() as session:
                user = await self.user_repo.get_by_id(user_id, session=session)
                if user is None:
                    raise UserNotFoundError(
                        "User not found for advertiser registration."
                    )

                profile = AdvertiserProfile(
                    user_id=user.user_id,
                    phone=phone,
                    brand=brand,
                    site_link=site_link,
                )
                await self.advertiser_repo.save(profile, session=session)

        if self.metrics_collector:
            self.metrics_collector.record_advertiser_registration(str(user.user_id))

        return profile

    async def get_profile(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        if self.transaction_manager is None:
            return await self.advertiser_repo.get_by_user_id(user_id)
        async with self.transaction_manager.transaction() as session:
            return await self.advertiser_repo.get_by_user_id(user_id, session=session)

    async def update_advertiser_profile(
        self,
        user_id: UUID,
        *,
        phone: Optional[str] = None,
        brand: Optional[str] = None,
        site_link: Optional[str] = None,
    ) -> Optional[AdvertiserProfile]:
        """Update advertiser profile fields. Returns updated profile or None if not found."""

        if self.transaction_manager is None:
            profile = await self.advertiser_repo.get_by_user_id(user_id)
        else:
            async with self.transaction_manager.transaction() as session:
                profile = await self.advertiser_repo.get_by_user_id(
                    user_id, session=session
                )
        if profile is None:
            return None

        updated = AdvertiserProfile(
            user_id=profile.user_id,
            phone=phone.strip() if phone is not None else profile.phone,
            brand=brand.strip() if brand is not None else profile.brand,
            site_link=(site_link or "").strip() or None
            if site_link is not None
            else profile.site_link,
        )
        if self.transaction_manager is None:
            await self.advertiser_repo.save(updated)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.advertiser_repo.save(updated, session=session)
        return updated
