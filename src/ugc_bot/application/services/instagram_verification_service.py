"""Service for Instagram verification."""

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID, uuid4

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramGraphApiClient,
    InstagramVerificationRepository,
    UserRepository,
)
from ugc_bot.domain.entities import BloggerProfile, InstagramVerificationCode, User

logger = logging.getLogger(__name__)


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    verification_repo: InstagramVerificationRepository
    instagram_api_client: InstagramGraphApiClient | None = None
    transaction_manager: TransactionManager | None = None

    async def get_notification_recipient(
        self, user_id: UUID
    ) -> tuple[Optional[User], Optional[BloggerProfile]]:
        """Fetch user and blogger profile for notification within a transaction."""

        if self.transaction_manager is None:
            user = await self.user_repo.get_by_id(user_id, session=None)
            if user is None:
                return (None, None)
            profile = await self.blogger_repo.get_by_user_id(user_id, session=None)
            return (user, profile)

        async with self.transaction_manager.transaction() as session:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                return (None, None)
            profile = await self.blogger_repo.get_by_user_id(user_id, session=session)
            return (user, profile)

    async def generate_code(self, user_id: UUID) -> InstagramVerificationCode:
        """Generate and store a new verification code."""

        if self.transaction_manager is None:
            if await self.user_repo.get_by_id(user_id) is None:
                raise UserNotFoundError("User not found for Instagram verification.")
        else:
            async with self.transaction_manager.transaction() as session:
                if await self.user_repo.get_by_id(user_id, session=session) is None:
                    raise UserNotFoundError(
                        "User not found for Instagram verification."
                    )

        code = _generate_code()
        now = datetime.now(timezone.utc)
        verification = InstagramVerificationCode(
            code_id=uuid4(),
            user_id=user_id,
            code=code,
            expires_at=now + timedelta(minutes=15),
            used=False,
            created_at=now,
        )
        if self.transaction_manager is None:
            await self.verification_repo.save(verification)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.verification_repo.save(verification, session=session)
        return verification

    async def verify_code(self, user_id: UUID, code: str) -> bool:
        """Validate code and confirm blogger profile."""

        if self.transaction_manager is None:
            profile = await self.blogger_repo.get_by_user_id(user_id)
            if profile is None:
                raise BloggerRegistrationError("Blogger profile not found.")

            valid_code = await self.verification_repo.get_valid_code(
                user_id, code.strip().upper()
            )
            if valid_code is None:
                return False

            await self.verification_repo.mark_used(valid_code.code_id)
            confirmed_profile = profile.__class__(
                user_id=profile.user_id,
                instagram_url=profile.instagram_url,
                confirmed=True,
                city=profile.city,
                topics=profile.topics,
                audience_gender=profile.audience_gender,
                audience_age_min=profile.audience_age_min,
                audience_age_max=profile.audience_age_max,
                audience_geo=profile.audience_geo,
                price=profile.price,
                barter=profile.barter,
                work_format=profile.work_format,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(confirmed_profile)
            return True

        async with self.transaction_manager.transaction() as session:
            profile = await self.blogger_repo.get_by_user_id(user_id, session=session)
            if profile is None:
                raise BloggerRegistrationError("Blogger profile not found.")

            valid_code = await self.verification_repo.get_valid_code(
                user_id, code.strip().upper(), session=session
            )
            if valid_code is None:
                return False

            await self.verification_repo.mark_used(valid_code.code_id, session=session)
            confirmed_profile = profile.__class__(
                user_id=profile.user_id,
                instagram_url=profile.instagram_url,
                confirmed=True,
                city=profile.city,
                topics=profile.topics,
                audience_gender=profile.audience_gender,
                audience_age_min=profile.audience_age_min,
                audience_age_max=profile.audience_age_max,
                audience_geo=profile.audience_geo,
                price=profile.price,
                barter=profile.barter,
                work_format=profile.work_format,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(confirmed_profile, session=session)
            return True

    async def verify_code_by_instagram_sender(
        self,
        instagram_sender_id: str,
        code: str,
        admin_instagram_username: str,
    ) -> UUID | None:
        """Verify code sent from Instagram webhook by sender ID.

        This method:
        1. Finds a valid code matching the provided code string
        2. Gets the user_id from the code
        3. Checks if the blogger profile's instagram_url matches the sender
        4. Confirms the profile if all checks pass

        Args:
            instagram_sender_id: Instagram user ID from webhook sender
            code: Verification code from message
            admin_instagram_username: Admin Instagram username (for logging)

        Returns:
            True if verification successful, False otherwise
        """
        code_upper = code.strip().upper()

        # Find valid code by code string
        if self.transaction_manager is None:
            valid_code = await self.verification_repo.get_valid_code_by_code(code_upper)
        else:
            async with self.transaction_manager.transaction() as session:
                valid_code = await self.verification_repo.get_valid_code_by_code(
                    code_upper, session=session
                )
        if valid_code is None:
            logger.debug("No valid code found for webhook verification")
            return None

        # Get blogger profile
        if self.transaction_manager is None:
            profile = await self.blogger_repo.get_by_user_id(valid_code.user_id)
        else:
            async with self.transaction_manager.transaction() as session:
                profile = await self.blogger_repo.get_by_user_id(
                    valid_code.user_id, session=session
                )
        if profile is None:
            logger.warning(
                "Blogger profile not found for verification code",
                extra={"user_id": valid_code.user_id},
            )
            return None

        # Extract Instagram username from instagram_url
        # instagram_url format: https://instagram.com/username or instagram.com/username
        instagram_url = profile.instagram_url.lower().strip()
        if "instagram.com/" in instagram_url:
            # Extract username from URL
            parts = instagram_url.split("instagram.com/")
            if len(parts) > 1:
                profile_username = parts[-1].split("/")[0].split("?")[0].strip()
            else:
                profile_username = None
        else:
            # Assume it's just the username
            profile_username = instagram_url.replace("@", "").strip()

        # Get username from Instagram Graph API
        api_username = None
        if self.instagram_api_client:
            try:
                api_username = await self.instagram_api_client.get_username_by_id(
                    instagram_sender_id
                )
            except Exception as exc:
                logger.warning(
                    "Failed to get username from Instagram API",
                    extra={"sender_id": instagram_sender_id, "error": str(exc)},
                    exc_info=exc,
                )

        # Verify username matches
        if api_username and profile_username:
            # Normalize usernames for comparison (case-insensitive)
            api_username_normalized = api_username.lower().strip()
            profile_username_normalized = profile_username.lower().strip()

            if api_username_normalized != profile_username_normalized:
                logger.warning(
                    "Instagram username mismatch",
                    extra={
                        "user_id": valid_code.user_id,
                        "sender_id": instagram_sender_id,
                        "api_username": api_username,
                        "profile_username": profile_username,
                    },
                )
                return None

        logger.info(
            "Verifying code from Instagram webhook",
            extra={
                "user_id": valid_code.user_id,
                "sender_id": instagram_sender_id,
                "api_username": api_username,
                "profile_username": profile_username,
            },
        )

        # Mark code as used and confirm profile
        if self.transaction_manager is None:
            await self.verification_repo.mark_used(valid_code.code_id)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.verification_repo.mark_used(
                    valid_code.code_id, session=session
                )
        confirmed_profile = profile.__class__(
            user_id=profile.user_id,
            instagram_url=profile.instagram_url,
            confirmed=True,
            city=profile.city,
            topics=profile.topics,
            audience_gender=profile.audience_gender,
            audience_age_min=profile.audience_age_min,
            audience_age_max=profile.audience_age_max,
            audience_geo=profile.audience_geo,
            price=profile.price,
            barter=profile.barter,
            work_format=profile.work_format,
            updated_at=datetime.now(timezone.utc),
        )
        if self.transaction_manager is None:
            await self.blogger_repo.save(confirmed_profile)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.blogger_repo.save(confirmed_profile, session=session)
        logger.info(
            "Instagram profile confirmed via webhook",
            extra={"user_id": str(valid_code.user_id)},
        )
        return valid_code.user_id


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
