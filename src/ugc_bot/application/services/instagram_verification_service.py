"""Service for Instagram verification."""

import logging
import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ugc_bot.application.services.user_role_service import UserRoleService

from ugc_bot.application.errors import (
    BloggerRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramGraphApiClient,
    InstagramProfileInfo,
    InstagramVerificationRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import (
    BloggerProfile,
    InstagramVerificationCode,
    User,
)
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


def _extract_username_from_instagram_url(instagram_url: str) -> str | None:
    """Extract username from instagram_url (instagram.com/user or @user)."""
    url = instagram_url.lower().strip()
    if "instagram.com/" in url:
        parts = url.split("instagram.com/")
        if len(parts) > 1:
            return parts[-1].split("/")[0].split("?")[0].strip()
        return None
    return url.replace("@", "").strip()


def _usernames_match(
    api_username: str | None, profile_username: str | None
) -> bool:
    """Return True if usernames match or API check skipped."""
    if not api_username or not profile_username:
        return True
    return api_username.lower().strip() == profile_username.lower().strip()


@dataclass(slots=True)
class VerificationSuccess:
    """Instagram verification succeeded; profile confirmed."""

    user_id: UUID


@dataclass(slots=True)
class VerificationMismatch:
    """Code and profile found but Instagram username does not match sender."""

    user_id: UUID
    profile_username: str | None
    api_username: str | None
    link_max_chat_id: str | None = None


@dataclass(slots=True)
class VerificationLinkSuccess:
    """Verification succeeded and Max account was linked."""

    user_id: UUID
    linked_user_id: UUID
    max_chat_id: str | None = None


@dataclass(slots=True)
class VerificationApiUnavailable:
    """Instagram API returned an error; cannot verify username match."""

    user_id: UUID


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    verification_repo: InstagramVerificationRepository
    instagram_api_client: InstagramGraphApiClient | None = None
    transaction_manager: TransactionManager | None = None
    user_role_service: "UserRoleService | None" = None

    async def _fetch_profile_and_username(
        self, instagram_sender_id: str
    ) -> tuple[Optional[InstagramProfileInfo], str | None]:
        """Fetch profile info and resolve username. Returns (info, username)."""
        profile_info: Optional[InstagramProfileInfo] = None
        if self.instagram_api_client:
            try:
                profile_info = (
                    await self.instagram_api_client.get_profile_by_id(
                        instagram_sender_id
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to get Instagram profile from API",
                    extra={
                        "sender_id": instagram_sender_id,
                        "error": str(exc),
                    },
                    exc_info=exc,
                )
        api_username = (
            profile_info.username
            if profile_info
            else await self._fetch_api_username(instagram_sender_id)
        )
        return profile_info, api_username

    async def _fetch_api_username(self, instagram_sender_id: str) -> str | None:
        """Fetch username from Instagram Graph API. Returns None on error."""
        if not self.instagram_api_client:
            return None
        try:
            return await self.instagram_api_client.get_username_by_id(
                instagram_sender_id
            )
        except Exception as exc:
            logger.warning(
                "Failed to get username from Instagram API",
                extra={"sender_id": instagram_sender_id, "error": str(exc)},
                exc_info=exc,
            )
            return None

    async def get_notification_recipient(
        self, user_id: UUID
    ) -> tuple[Optional[User], Optional[BloggerProfile]]:
        """Fetch user and blogger profile for notification in a transaction."""

        async def _run(session: object | None):
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                return (None, None)
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=session
            )
            return (user, profile)

        return await with_optional_tx(self.transaction_manager, _run)

    async def generate_code(
        self,
        user_id: UUID,
        link_max_id: str | None = None,
        link_max_chat_id: str | None = None,
        link_username: str | None = None,
        link_phone: str | None = None,
    ) -> InstagramVerificationCode:
        """Generate and store a new verification code."""

        async def _run(session: object | None) -> InstagramVerificationCode:
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
                link_max_id=link_max_id,
                link_max_chat_id=link_max_chat_id,
                link_username=link_username,
                link_phone=link_phone,
            )
            await self.verification_repo.save(verification, session=session)
            return verification

        return await with_optional_tx(self.transaction_manager, _run)

    async def verify_code(
        self, user_id: UUID, code: str
    ) -> bool | VerificationLinkSuccess:
        """Validate code and confirm blogger profile.

        Returns True on normal verification, VerificationLinkSuccess if
        the code carried linking metadata, or False if the code is invalid.
        """

        async def _run(
            session: object | None,
        ) -> bool | VerificationLinkSuccess:
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                raise BloggerRegistrationError("Blogger profile not found.")

            valid_code = await self.verification_repo.get_valid_code(
                user_id, code.strip().upper(), session=session
            )
            if valid_code is None:
                return False

            await self.verification_repo.mark_used(
                valid_code.code_id, session=session
            )
            confirmed_profile = replace(
                profile,
                confirmed=True,
                updated_at=datetime.now(timezone.utc),
            )
            await self.blogger_repo.save(confirmed_profile, session=session)

            link_result = await self._try_link_max_account(
                valid_code, profile.instagram_url or "", session=session
            )
            if link_result:
                return link_result
            return True

        return await with_optional_tx(self.transaction_manager, _run)

    async def _try_link_max_account(
        self,
        valid_code: InstagramVerificationCode,
        instagram_url: str,
        session: object | None = None,
    ) -> VerificationLinkSuccess | None:
        """Attempt to link Max account after verification."""
        if not valid_code.link_max_id or not self.user_role_service:
            return None
        linked = await self.user_role_service.link_max_account(
            max_id=valid_code.link_max_id,
            instagram_url=instagram_url,
            username=valid_code.link_username or "",
            max_chat_id=valid_code.link_max_chat_id,
            session=session,
        )
        if linked:
            if valid_code.link_phone:
                profile = await self.blogger_repo.get_by_user_id(
                    valid_code.user_id, session=session
                )
                if profile and not profile.phone:
                    updated = replace(profile, phone=valid_code.link_phone)
                    await self.blogger_repo.save(updated, session=session)
            return VerificationLinkSuccess(
                user_id=valid_code.user_id,
                linked_user_id=linked.user_id,
                max_chat_id=valid_code.link_max_chat_id,
            )
        return None

    async def verify_code_by_instagram_sender(
        self,
        instagram_sender_id: str,
        code: str,
        admin_instagram_username: str,
    ) -> (
        VerificationSuccess
        | VerificationLinkSuccess
        | VerificationMismatch
        | VerificationApiUnavailable
        | None
    ):
        """Verify code sent from Instagram webhook by sender ID.

        This method:
        1. Finds a valid code matching the provided code string
        2. Gets the user_id from the code
        3. Checks if the blogger profile's instagram_url matches the sender
        4. Confirms the profile if all checks pass; otherwise returns mismatch.

        Args:
            instagram_sender_id: Instagram user ID from webhook sender
            code: Verification code from message
            admin_instagram_username: Admin Instagram username (for logging)

        Returns:
            VerificationSuccess on success, VerificationMismatch when usernames
            do not match, None when code or profile not found.
        """
        code_upper = code.strip().upper()

        async def _get_valid_code(session: object | None):
            return await self.verification_repo.get_valid_code_by_code(
                code_upper, session=session
            )

        valid_code = await with_optional_tx(
            self.transaction_manager, _get_valid_code
        )
        if valid_code is None:
            logger.debug("No valid code found for webhook verification")
            return None

        async def _get_profile(session: object | None):
            return await self.blogger_repo.get_by_user_id(
                valid_code.user_id, session=session
            )

        profile = await with_optional_tx(self.transaction_manager, _get_profile)
        if profile is None:
            logger.warning(
                "Blogger profile not found for verification code",
                extra={"user_id": valid_code.user_id},
            )
            return None

        profile_username = _extract_username_from_instagram_url(
            profile.instagram_url
        )
        profile_info, api_username = await self._fetch_profile_and_username(
            instagram_sender_id
        )

        if not api_username and self.instagram_api_client:
            logger.warning(
                "Instagram API unavailable during verification",
                extra={
                    "user_id": str(valid_code.user_id),
                    "sender_id": instagram_sender_id,
                },
            )
            return VerificationApiUnavailable(user_id=valid_code.user_id)

        if not _usernames_match(api_username, profile_username):
            logger.warning(
                "Instagram username mismatch",
                extra={
                    "user_id": valid_code.user_id,
                    "sender_id": instagram_sender_id,
                    "api_username": api_username,
                    "profile_username": profile_username,
                },
            )
            return VerificationMismatch(
                user_id=valid_code.user_id,
                profile_username=profile_username,
                api_username=api_username,
                link_max_chat_id=valid_code.link_max_chat_id,
            )

        now = datetime.now(timezone.utc)
        instagram_user_id = instagram_sender_id
        instagram_followers_count = None
        instagram_username = None
        instagram_stats_fetched_at = None
        if profile_info:
            instagram_followers_count = profile_info.followers_count
            instagram_username = profile_info.username
            instagram_stats_fetched_at = now

        async def _confirm(
            session: object | None,
        ) -> VerificationLinkSuccess | None:
            await self.verification_repo.mark_used(
                valid_code.code_id, session=session
            )
            confirmed_profile = replace(
                profile,
                confirmed=True,
                updated_at=now,
                instagram_user_id=instagram_user_id,
                instagram_followers_count=instagram_followers_count,
                instagram_username=instagram_username,
                instagram_stats_fetched_at=instagram_stats_fetched_at,
            )
            await self.blogger_repo.save(confirmed_profile, session=session)
            return await self._try_link_max_account(
                valid_code, profile.instagram_url or "", session=session
            )

        link_result = await with_optional_tx(self.transaction_manager, _confirm)
        logger.info(
            "Instagram verification success",
            extra={
                "user_id": str(valid_code.user_id),
                "instagram_user_id": instagram_sender_id,
                "username": api_username,
            },
        )
        return link_result or VerificationSuccess(user_id=valid_code.user_id)


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
