"""Service for Instagram verification."""

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.ports import (
    InstagramGraphApiClient,
    InstagramVerificationRepository,
    UserRepository,
)
from ugc_bot.domain.entities import InstagramVerificationCode, User

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    verification_repo: InstagramVerificationRepository
    instagram_api_client: InstagramGraphApiClient | None = None

    def generate_code(self, user_id: UUID) -> InstagramVerificationCode:
        """Generate and store a new verification code."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found for Instagram verification.")

        if not user.instagram_url:
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

        if not user.instagram_url:
            raise UserNotFoundError("User has no Instagram URL to verify.")

        valid_code = self.verification_repo.get_valid_code(
            user_id, code.strip().upper()
        )
        if valid_code is None:
            return False

        self.verification_repo.mark_used(valid_code.code_id)

        confirmed_user = _with_confirmed_instagram(user)
        self.user_repo.save(confirmed_user)

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

        # Get user
        user = self.user_repo.get_by_id(valid_code.user_id)
        if user is None:
            logger.warning(
                "User not found for verification code",
                extra={"user_id": valid_code.user_id},
            )
            return None

        profile_username = _extract_instagram_username(user.instagram_url)
        if not profile_username:
            logger.warning(
                "User has no Instagram URL for verification",
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

        confirmed_user = _with_confirmed_instagram(user)
        self.user_repo.save(confirmed_user)

        logger.info(
            "Instagram profile confirmed via webhook",
            extra={
                "user_id": str(valid_code.user_id),
                "profile_type": "user",
            },
        )
        return valid_code.user_id


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _extract_instagram_username(instagram_url: str | None) -> str | None:
    """Extract username from an Instagram URL or handle."""

    if not instagram_url:
        return None
    instagram_url = instagram_url.lower().strip()
    if "instagram.com/" in instagram_url:
        parts = instagram_url.split("instagram.com/")
        if len(parts) > 1:
            return parts[-1].split("/")[0].split("?")[0].strip() or None
        return None
    return instagram_url.replace("@", "").strip() or None


def _with_confirmed_instagram(user: User) -> User:
    """Return a user with Instagram confirmed."""

    return User(
        user_id=user.user_id,
        external_id=user.external_id,
        messenger_type=user.messenger_type,
        username=user.username,
        role=user.role,
        status=user.status,
        issue_count=user.issue_count,
        created_at=user.created_at,
        instagram_url=user.instagram_url,
        confirmed=True,
        topics=user.topics,
        audience_gender=user.audience_gender,
        audience_age_min=user.audience_age_min,
        audience_age_max=user.audience_age_max,
        audience_geo=user.audience_geo,
        price=user.price,
        contact=user.contact,
        profile_updated_at=user.profile_updated_at,
    )
