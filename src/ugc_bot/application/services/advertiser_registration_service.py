"""Service for advertiser registration."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
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
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.domain.entities import AdvertiserProfile
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class AdvertiserRegistrationService:
    """Register advertiser profiles with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    referral_service: Optional[ReferralService] = None
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def register_advertiser(
        self,
        user_id: UUID,
        phone: str,
        brand: str,
        site_link: Optional[str] = None,
        city: Optional[str] = None,
        company_activity: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> AdvertiserProfile:
        """Create an advertiser profile after validating input.

        Updates user.role_chosen_at and optionally user.username (display_name)
        in the same transaction as profile creation.
        """

        phone = phone.strip()
        brand = brand.strip()
        site_link = (site_link or "").strip() or None
        city = (city or "").strip() or None
        company_activity = (company_activity or "").strip() or None
        if not phone:
            raise AdvertiserRegistrationError("Phone is required.")
        if not brand:
            raise AdvertiserRegistrationError("Brand is required.")

        async def _run(session: object | None) -> AdvertiserProfile:
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
                city=city,
                company_activity=company_activity,
            )
            await self.advertiser_repo.save(profile, session=session)

            now = datetime.now(timezone.utc)
            updated_user = replace(
                user,
                username=(
                    display_name.strip()
                    if display_name and display_name.strip()
                    else user.username
                ),
                role_chosen_at=(
                    now if user.role_chosen_at is None else user.role_chosen_at
                ),
                agreement_confirmed_at=now,
            )
            await self.user_repo.save(updated_user, session=session)

            if self.referral_service:
                await self.referral_service.create_binding_from_pending(
                    creator_user_id=user_id,
                    session=session,
                )

            if self.metrics_collector:
                self.metrics_collector.record_advertiser_registration(
                    str(user.user_id)
                )

            return profile

        return await with_optional_tx(self.transaction_manager, _run)

    async def save_advertiser_before_agreement(
        self,
        user_id: UUID,
        phone: str,
        brand: str,
        site_link: Optional[str] = None,
        city: Optional[str] = None,
        company_activity: Optional[str] = None,
        display_name: Optional[str] = None,
        telegram_username: Optional[str] = None,
    ) -> AdvertiserProfile:
        """Save advertiser profile and update user before consent confirmation.

        Does not set agreement_confirmed_at and does not run referral/metrics.
        When telegram_username is provided, updates user.telegram.
        """
        phone = phone.strip()
        brand = brand.strip()
        site_link = (site_link or "").strip() or None
        city = (city or "").strip() or None
        company_activity = (company_activity or "").strip() or None
        if not phone:
            raise AdvertiserRegistrationError("Phone is required.")
        if not brand:
            raise AdvertiserRegistrationError("Brand is required.")

        async def _run(session: object | None) -> AdvertiserProfile:
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
                city=city,
                company_activity=company_activity,
            )
            await self.advertiser_repo.save(profile, session=session)

            now = datetime.now(timezone.utc)
            updated_user = replace(
                user,
                username=(
                    display_name.strip()
                    if display_name and display_name.strip()
                    else user.username
                ),
                role_chosen_at=(
                    now if user.role_chosen_at is None else user.role_chosen_at
                ),
                telegram=(
                    telegram_username
                    if telegram_username is not None
                    else user.telegram
                ),
                agreement_confirmed_at=None,
            )
            await self.user_repo.save(updated_user, session=session)
            return profile

        return await with_optional_tx(self.transaction_manager, _run)

    async def confirm_advertiser_agreement(self, user_id: UUID) -> None:
        """Set agreement_confirmed_at and run referral/metrics."""

        async def _run(session: object | None) -> None:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError(
                    "User not found for agreement confirmation."
                )
            now = datetime.now(timezone.utc)
            updated_user = replace(user, agreement_confirmed_at=now)
            await self.user_repo.save(updated_user, session=session)

            if self.referral_service:
                await self.referral_service.create_binding_from_pending(
                    creator_user_id=user_id,
                    session=session,
                )

            if self.metrics_collector:
                self.metrics_collector.record_advertiser_registration(
                    str(user.user_id)
                )

        await with_optional_tx(self.transaction_manager, _run)

    async def get_profile(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        async def _run(session: object | None):
            return await self.advertiser_repo.get_by_user_id(
                user_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def update_advertiser_profile(
        self,
        user_id: UUID,
        *,
        phone: Optional[str] = None,
        brand: Optional[str] = None,
        site_link: Optional[str] = None,
        city: Optional[str] = None,
        company_activity: Optional[str] = None,
    ) -> Optional[AdvertiserProfile]:
        """Update advertiser profile. Returns profile or None if not found."""

        async def _run(session: object | None) -> Optional[AdvertiserProfile]:
            profile = await self.advertiser_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                return None

            updated = replace(
                profile,
                phone=phone.strip() if phone is not None else profile.phone,
                brand=brand.strip() if brand is not None else profile.brand,
                site_link=(site_link or "").strip() or None
                if site_link is not None
                else profile.site_link,
                city=(city or "").strip() or None
                if city is not None
                else profile.city,
                company_activity=(company_activity or "").strip() or None
                if company_activity is not None
                else profile.company_activity,
            )
            await self.advertiser_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)
