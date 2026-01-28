"""Service for advertiser registration."""

from dataclasses import dataclass
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import AdvertiserProfileRepository, UserRepository
from ugc_bot.domain.entities import AdvertiserProfile


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


@dataclass(slots=True)
class AdvertiserRegistrationService:
    """Register advertiser profiles with validation."""

    user_repo: UserRepository
    advertiser_repo: AdvertiserProfileRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def register_advertiser(
        self, user_id: UUID, contact: str
    ) -> AdvertiserProfile:
        """Create an advertiser profile after validating input."""

        if self.transaction_manager is None:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError("User not found for advertiser registration.")

            contact = contact.strip()
            if not contact:
                raise AdvertiserRegistrationError("Contact is required.")

            profile = AdvertiserProfile(user_id=user.user_id, contact=contact)
            await self.advertiser_repo.save(profile)
        else:
            async with self.transaction_manager.transaction() as session:
                user = await self.user_repo.get_by_id(user_id, session=session)
                if user is None:
                    raise UserNotFoundError(
                        "User not found for advertiser registration."
                    )

                contact = contact.strip()
                if not contact:
                    raise AdvertiserRegistrationError("Contact is required.")

                profile = AdvertiserProfile(user_id=user.user_id, contact=contact)
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
