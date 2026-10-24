"""Service for Instagram verification."""

import logging
import re
import secrets
import string
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional, overload
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ugc_bot.application.services.user_role_service import UserRoleService

from ugc_bot.application.errors import (
    BloggerRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.identity_history_ports import (
    IdentityEvidence,
    identity_evidence,
)
from ugc_bot.application.legacy_link_ports import (
    LegacyMaxPreparation,
    validated_max_chat_id,
)
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramGraphApiClient,
    InstagramProfileInfo,
    InstagramVerificationRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.application.services.social_account_service import (
    instagram_account,
)
from ugc_bot.application.social_ports import SocialAccountRepository
from ugc_bot.domain.entities import (
    BloggerProfile,
    InstagramVerificationCode,
    User,
)
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{8})(?![A-Z0-9])")


def _extract_code_from_text(text: str) -> str | None:
    """Extract an 8-char [A-Z0-9] verification code from arbitrary text.

    Handles cases where a blogger sends the code mixed with greetings or
    other words, e.g. "Привет ABC123XY" or "ABC123XY, подтвердите".
    """
    m = _CODE_RE.search(text)
    return m.group(1) if m else None


def _extract_username_from_instagram_url(instagram_url: str) -> str | None:
    """Extract a nonblank Instagram handle from a URL or native handle."""
    value = (instagram_url or "").lower().strip()
    if "instagram.com/" in value:
        value = (
            value.rsplit("instagram.com/", 1)[1]
            .split("/", 1)[0]
            .split("?", 1)[0]
        )
    else:
        value = value.removeprefix("@")
    return value if re.fullmatch(r"[a-z0-9_.]{1,30}", value) else None


def _usernames_match(
    api_username: str | None, profile_username: str | None
) -> bool:
    """Only two nonblank proven usernames can match."""
    if not (api_username or "").strip() or not (profile_username or "").strip():
        return False
    return (api_username or "").lower().strip() == (
        profile_username or ""
    ).lower().strip()


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
class VerificationLinkConflict:
    """Instagram confirmed and code consumed; separate accounts preserved."""

    user_id: UUID
    max_chat_id: str | None
    reason: str
    locale: str = "ru"


@dataclass(slots=True)
class VerificationLinkUnavailable:
    """Instagram confirmed and code consumed; attachment was unavailable."""

    user_id: UUID
    max_chat_id: str | None
    reason: str
    locale: str = "ru"


@dataclass(slots=True)
class VerificationApiUnavailable:
    """Instagram API returned an error; cannot verify username match."""

    user_id: UUID


@dataclass(slots=True)
class VerificationUnavailable:
    """No confirmation or code consumption; preparation was unavailable."""

    user_id: UUID
    reason: str


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    verification_repo: InstagramVerificationRepository
    instagram_api_client: InstagramGraphApiClient | None = None
    transaction_manager: TransactionManager | None = None
    user_role_service: "UserRoleService | None" = None
    social_repo: SocialAccountRepository | None = None

    async def _save_social(
        self,
        profile: BloggerProfile,
        *,
        source: str,
        session: object | None,
    ) -> None:
        if (
            self.social_repo is None
            or not (profile.instagram_user_id or "").strip()
        ):
            return
        account = instagram_account(profile)
        observed_at = datetime.now(timezone.utc)
        await self.social_repo.save(
            replace(
                account,
                metrics_source=source
                if account.followers_count is not None
                else None,
                verified_at=observed_at
                if source == "instagram_graph_api"
                else None,
                verification_observed_at=observed_at,
                verification_source="instagram_webhook"
                if source == "instagram_graph_api"
                else "manual_code",
            ),
            session=session,
        )

    async def _fetch_profile_and_username(
        self, instagram_sender_id: str
    ) -> tuple[Optional[InstagramProfileInfo], str | None]:
        """Require an actual successful profile response."""
        if self.instagram_api_client is None:
            return None, None
        try:
            profile = await self.instagram_api_client.get_profile_by_id(
                instagram_sender_id
            )
        except Exception:
            logger.warning("Instagram profile proof unavailable")
            return None, None
        username = (
            (profile.username or "").strip() if profile is not None else ""
        )
        return (profile, username) if username else (None, None)

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
    ) -> (
        bool
        | VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | VerificationUnavailable
    ):
        """Confirm manual-code evidence under the same prepared transaction."""

        async def _run(session):
            profile = await self.blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                raise BloggerRegistrationError("Blogger profile not found.")
            expected = await self.verification_repo.get_valid_code(
                user_id, code.strip().upper(), session=session
            )
            if expected is None:
                return False
            result = await self._confirm_prepared(expected, session=session)
            if isinstance(result, VerificationSuccess):
                return True
            return False if result is None else result

        return await with_optional_tx(self.transaction_manager, _run)

    def _participants(self) -> tuple[object, ...]:
        return (self.user_repo, self.blogger_repo, self.verification_repo) + (
            (self.social_repo,) if self.social_repo is not None else ()
        )

    @staticmethod
    def _sender_outcome(
        profile: BloggerProfile,
        profile_info: InstagramProfileInfo | None,
        api_username: str | None,
        preparation: LegacyMaxPreparation,
    ) -> VerificationApiUnavailable | VerificationMismatch | None:
        expected_username = _extract_username_from_instagram_url(
            profile.instagram_url or ""
        )
        if (
            profile_info is None
            or not (api_username or "").strip()
            or not (expected_username or "").strip()
        ):
            return VerificationApiUnavailable(preparation.target_id)
        if not _usernames_match(api_username, expected_username):
            return VerificationMismatch(
                preparation.target_id,
                expected_username,
                api_username,
                preparation.max_chat_id,
            )
        return None

    @overload
    async def _confirm_prepared(
        self,
        expected: InstagramVerificationCode,
        *,
        session: object | None,
        sender: None = None,
        profile_info: None = None,
        api_username: None = None,
    ) -> (
        VerificationSuccess
        | VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | VerificationUnavailable
        | None
    ): ...

    @overload
    async def _confirm_prepared(
        self,
        expected: InstagramVerificationCode,
        *,
        session: object | None,
        sender: str,
        profile_info: InstagramProfileInfo,
        api_username: str,
    ) -> (
        VerificationSuccess
        | VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | VerificationUnavailable
        | VerificationApiUnavailable
        | VerificationMismatch
        | None
    ): ...

    async def _confirm_prepared(
        self,
        expected: InstagramVerificationCode,
        *,
        session: object | None,
        sender: str | None = None,
        profile_info: InstagramProfileInfo | None = None,
        api_username: str | None = None,
    ) -> (
        VerificationSuccess
        | VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | VerificationUnavailable
        | VerificationApiUnavailable
        | VerificationMismatch
        | None
    ):
        if not self.user_repo.legacy_confirmation_supported(
            session, self._participants()
        ):
            return VerificationUnavailable(
                expected.user_id, "transaction_unavailable"
            )
        preparation = await self.user_repo.prepare_legacy_max_attachment(
            expected.user_id,
            code_id=expected.code_id,
            max_id=expected.link_max_id,
            max_chat_id=expected.link_max_chat_id,
            session=session,
        )
        if not preparation.protected:
            return VerificationUnavailable(expected.user_id, preparation.reason)
        current = await self.verification_repo.current_legacy_code(
            expected.code_id,
            expected.user_id,
            expected.code,
            session=session,
        )
        if current is None:
            return None
        scope = (
            "code_id",
            "user_id",
            "code",
            "link_max_id",
            "link_max_chat_id",
            "link_username",
            "link_phone",
        )
        if any(
            getattr(current, key) != getattr(expected, key) for key in scope
        ):
            return VerificationUnavailable(
                expected.user_id, "verification_scope_changed"
            )
        profile = await self.blogger_repo.current_legacy_profile(
            expected.user_id, session=session
        )
        if profile is None:
            return VerificationUnavailable(expected.user_id, "profile_missing")
        if current.expires_at <= datetime.now(timezone.utc):
            return None
        if sender is not None:
            unavailable = self._sender_outcome(
                profile, profile_info, api_username, preparation
            )
            if unavailable is not None:
                return unavailable
        now = datetime.now(timezone.utc)
        confirmed = replace(profile, confirmed=True, updated_at=now)
        if sender is not None:
            assert profile_info is not None
            confirmed = replace(
                confirmed,
                instagram_user_id=sender,
                instagram_followers_count=profile_info.followers_count,
                instagram_username=api_username,
                instagram_stats_fetched_at=now,
            )
        source = "instagram_webhook" if sender is not None else "manual_code"
        with identity_evidence(
            IdentityEvidence(source, str(current.code_id), now)
        ):
            await self.blogger_repo.save(confirmed, session=session)
        await self._save_social(
            confirmed,
            source="instagram_graph_api"
            if sender is not None
            else "legacy_profile",
            session=session,
        )
        await self.verification_repo.mark_used(current.code_id, session=session)
        linked = await self._try_link_max_account(
            current, preparation, confirmed, session=session
        )
        return (
            VerificationSuccess(current.user_id) if linked is None else linked
        )

    async def _try_link_max_account(
        self,
        valid_code: InstagramVerificationCode,
        preparation: LegacyMaxPreparation,
        profile: BloggerProfile,
        *,
        session: object | None,
    ) -> (
        VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | None
    ):
        metadata = (
            valid_code.link_max_id,
            valid_code.link_max_chat_id,
            valid_code.link_username,
            valid_code.link_phone,
        )
        if all(value is None for value in metadata):
            return None
        chat_id = validated_max_chat_id(valid_code.link_max_chat_id)
        if preparation.state == "conflict":
            return VerificationLinkConflict(
                valid_code.user_id,
                chat_id,
                preparation.reason,
                preparation.locale,
            )
        if preparation.state == "unavailable" or not valid_code.link_max_id:
            return VerificationLinkUnavailable(
                valid_code.user_id,
                chat_id,
                preparation.reason or "native_identity_invalid",
                preparation.locale,
            )
        if self.user_role_service is None:
            return VerificationLinkUnavailable(
                valid_code.user_id,
                chat_id,
                "linking_service_missing",
                preparation.locale,
            )
        linked = await self.user_role_service.attach_verified_max(
            preparation, session=session
        )
        if linked.state == "conflict":
            return VerificationLinkConflict(
                valid_code.user_id, chat_id, linked.reason, preparation.locale
            )
        if linked.state not in ("ready", "same_account") or linked.user is None:
            return VerificationLinkUnavailable(
                valid_code.user_id,
                chat_id,
                linked.reason or "attachment_unavailable",
                preparation.locale,
            )
        if (
            linked.state == "ready"
            and linked.reason == "attached"
            and not profile.phone
        ):
            phone = valid_code.link_phone
            if (
                isinstance(phone, str)
                and re.fullmatch(r"\+?[0-9 ()-]{7,32}", phone)
                and 7 <= len(re.sub(r"\D", "", phone)) <= 15
            ):
                await self.blogger_repo.save(
                    replace(profile, phone=phone), session=session
                )
        return VerificationLinkSuccess(
            valid_code.user_id, linked.user.user_id, preparation.max_chat_id
        )

    async def verify_code_by_instagram_sender(
        self,
        instagram_sender_id: str,
        code: str,
        admin_instagram_username: str,
    ) -> (
        VerificationSuccess
        | VerificationLinkSuccess
        | VerificationLinkConflict
        | VerificationLinkUnavailable
        | VerificationUnavailable
        | VerificationMismatch
        | VerificationApiUnavailable
        | None
    ):
        """Fetch external proof before the confirmation transaction."""
        code_upper = (
            _extract_code_from_text(code.strip().upper())
            or code.strip().upper()
        )

        async def _discover(session):
            return await self.verification_repo.get_valid_code_by_code(
                code_upper, session=session
            )

        expected = await with_optional_tx(self.transaction_manager, _discover)
        if expected is None:
            return None
        profile_info, api_username = await self._fetch_profile_and_username(
            instagram_sender_id
        )
        if profile_info is None or not api_username:
            return VerificationApiUnavailable(expected.user_id)

        async def _confirm(session):
            return await self._confirm_prepared(
                expected,
                session=session,
                sender=instagram_sender_id,
                profile_info=profile_info,
                api_username=api_username,
            )

        return await with_optional_tx(self.transaction_manager, _confirm)


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
