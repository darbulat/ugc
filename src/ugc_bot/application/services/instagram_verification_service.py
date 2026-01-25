"""Service for Instagram verification."""

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    InstagramGraphApiClient,
    InstagramVerificationRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    InstagramVerificationCode,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    advertiser_repo: AdvertiserProfileRepository
    verification_repo: InstagramVerificationRepository
    instagram_api_client: InstagramGraphApiClient | None = None

    def generate_code(self, user_id: UUID) -> InstagramVerificationCode:
        """Generate and store a new verification code."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for Instagram verification.")

        # Check if user has a profile with Instagram URL
        blogger_profile = self.blogger_repo.get_by_user_id(user_id)
        advertiser_profile = self.advertiser_repo.get_by_user_id(user_id)

        if blogger_profile is None and advertiser_profile is None:
            raise UserNotFoundError("User has no profile for Instagram verification.")

        # Check if at least one profile has Instagram URL
        has_instagram = (
            blogger_profile is not None and blogger_profile.instagram_url
        ) or (advertiser_profile is not None and advertiser_profile.instagram_url)
        if not has_instagram:
            raise UserNotFoundError("User has no Instagram URL to verify.")

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
        self.verification_repo.save(verification)
        return verification

    def verify_code(self, user_id: UUID, code: str) -> bool:
        """Validate code and confirm user Instagram in profile."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found.")

        # Check profiles
        blogger_profile = self.blogger_repo.get_by_user_id(user_id)
        advertiser_profile = self.advertiser_repo.get_by_user_id(user_id)

        if blogger_profile is None and advertiser_profile is None:
            raise UserNotFoundError("User has no profile for Instagram verification.")

        # Check if at least one profile has Instagram URL
        has_instagram = (
            blogger_profile is not None and blogger_profile.instagram_url
        ) or (advertiser_profile is not None and advertiser_profile.instagram_url)
        if not has_instagram:
            raise UserNotFoundError("User has no Instagram URL to verify.")

        valid_code = self.verification_repo.get_valid_code(
            user_id, code.strip().upper()
        )
        if valid_code is None:
            return False

        self.verification_repo.mark_used(valid_code.code_id)

        # Update confirmed status in profiles that have Instagram URL
        if blogger_profile is not None and blogger_profile.instagram_url:
            confirmed_blogger = blogger_profile.__class__(
                user_id=blogger_profile.user_id,
                instagram_url=blogger_profile.instagram_url,
                confirmed=True,
                topics=blogger_profile.topics,
                audience_gender=blogger_profile.audience_gender,
                audience_age_min=blogger_profile.audience_age_min,
                audience_age_max=blogger_profile.audience_age_max,
                audience_geo=blogger_profile.audience_geo,
                price=blogger_profile.price,
                updated_at=blogger_profile.updated_at,
            )
            self.blogger_repo.save(confirmed_blogger)

        if advertiser_profile is not None and advertiser_profile.instagram_url:
            confirmed_advertiser = advertiser_profile.__class__(
                user_id=advertiser_profile.user_id,
                instagram_url=advertiser_profile.instagram_url,
                confirmed=True,
                contact=advertiser_profile.contact,
            )
            self.advertiser_repo.save(confirmed_advertiser)

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
        3. Checks if the user's instagram_url matches the sender
        4. Confirms the user if all checks pass

        Args:
            instagram_sender_id: Instagram user ID from webhook sender
            code: Verification code from message
            admin_instagram_username: Admin Instagram username (for logging)

        Returns:
            user_id if verification successful, None otherwise
        """
        code_upper = code.strip().upper()

        # Find valid code by code string
        valid_code = self.verification_repo.get_valid_code_by_code(code_upper)
        if valid_code is None:
            logger.debug("No valid code found for webhook verification")
            return None

        # Get user and profiles
        user = self.user_repo.get_by_id(valid_code.user_id)
        if user is None:
            logger.warning(
                "User not found for verification code",
                extra={"user_id": valid_code.user_id},
            )
            return None

        blogger_profile = self.blogger_repo.get_by_user_id(valid_code.user_id)
        advertiser_profile = self.advertiser_repo.get_by_user_id(valid_code.user_id)

        # Find profile with matching Instagram URL
        matching_profile_type: str | None = None
        matching_profile: BloggerProfile | AdvertiserProfile | None = None
        profile_username: str | None = None

        if blogger_profile and blogger_profile.instagram_url:
            instagram_url = blogger_profile.instagram_url.lower().strip()
            if "instagram.com/" in instagram_url:
                parts = instagram_url.split("instagram.com/")
                if len(parts) > 1:
                    profile_username = parts[-1].split("/")[0].split("?")[0].strip()
            else:
                profile_username = instagram_url.replace("@", "").strip()
            matching_profile_type = "blogger"
            matching_profile = blogger_profile

        if advertiser_profile and advertiser_profile.instagram_url:
            instagram_url = advertiser_profile.instagram_url.lower().strip()
            if "instagram.com/" in instagram_url:
                parts = instagram_url.split("instagram.com/")
                if len(parts) > 1:
                    adv_username = parts[-1].split("/")[0].split("?")[0].strip()
                else:
                    adv_username = None
            else:
                adv_username = instagram_url.replace("@", "").strip()

            # Use advertiser profile if it matches, or if no blogger profile matched
            if matching_profile_type is None or adv_username == profile_username:
                profile_username = adv_username
                matching_profile_type = "advertiser"
                matching_profile = advertiser_profile

        if (
            matching_profile_type is None
            or matching_profile is None
            or not profile_username
        ):
            logger.warning(
                "User has no Instagram URL in profiles for verification",
                extra={"user_id": valid_code.user_id},
            )
            return None

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
        self.verification_repo.mark_used(valid_code.code_id)

        if matching_profile_type == "blogger" and isinstance(
            matching_profile, BloggerProfile
        ):
            confirmed_blogger = BloggerProfile(
                user_id=matching_profile.user_id,
                instagram_url=matching_profile.instagram_url,
                confirmed=True,
                topics=matching_profile.topics,
                audience_gender=matching_profile.audience_gender,
                audience_age_min=matching_profile.audience_age_min,
                audience_age_max=matching_profile.audience_age_max,
                audience_geo=matching_profile.audience_geo,
                price=matching_profile.price,
                updated_at=matching_profile.updated_at,
            )
            self.blogger_repo.save(confirmed_blogger)
        elif matching_profile_type == "advertiser" and isinstance(
            matching_profile, AdvertiserProfile
        ):
            confirmed_advertiser = AdvertiserProfile(
                user_id=matching_profile.user_id,
                instagram_url=matching_profile.instagram_url,
                confirmed=True,
                contact=matching_profile.contact,
            )
            self.advertiser_repo.save(confirmed_advertiser)

        logger.info(
            "Instagram profile confirmed via webhook",
            extra={
                "user_id": str(valid_code.user_id),
                "profile_type": matching_profile_type,
            },
        )
        return valid_code.user_id


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
