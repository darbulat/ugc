"""Service for user creation and lookup."""

import logging
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)

REFERRAL_CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
REFERRAL_CODE_LENGTH = 8
REFERRAL_CODE_MAX_ATTEMPTS = 10

_IG_USERNAME_RE = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)",
)


def _extract_instagram_username(url: str) -> str | None:
    """Extract the Instagram username from a URL."""
    m = _IG_USERNAME_RE.search(url)
    return m.group(1).lower() if m else None


@dataclass(slots=True)
class UserRoleService:
    """Manage user creation and lookup."""

    user_repo: UserRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    blogger_profile_repo: BloggerProfileRepository | None = None

    async def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
        role_chosen: bool = False,
        telegram_username: str | None = None,
        max_chat_id: str | None = None,
    ) -> User:
        """Create or update a user.

        Args:
            external_id: External messenger id.
            messenger_type: Messenger type.
            username: Display username (name shown to advertisers).
            role_chosen: If True, set role_chosen_at to now when still unset.
            telegram_username: Telegram alias (@username), admin-only.
        """

        async def _run(session: object | None) -> User:
            existing = await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )
            now = datetime.now(timezone.utc)
            if existing:
                status = existing.status
                role_chosen_at = (
                    now
                    if role_chosen and existing.role_chosen_at is None
                    else existing.role_chosen_at
                )
                telegram = (
                    telegram_username
                    if telegram_username is not None
                    else existing.telegram
                )
                update_kwargs: dict = {
                    "username": username,
                    "status": status,
                    "role_chosen_at": role_chosen_at,
                    "telegram": telegram,
                }
                if max_chat_id is not None:
                    update_kwargs["max_chat_id"] = max_chat_id
                updated = replace(existing, **update_kwargs)
                await self.user_repo.save(updated, session=session)
                return updated

            status = UserStatus.ACTIVE
            role_chosen_at = now if role_chosen else None
            referral_code = await self._generate_unique_referral_code(session)
            new_user = User(
                user_id=uuid4(),
                messenger_type=messenger_type,
                username=username,
                status=status,
                issue_count=0,
                created_at=now,
                telegram_id=(
                    external_id
                    if messenger_type == MessengerType.TELEGRAM
                    else None
                ),
                max_id=(
                    external_id if messenger_type == MessengerType.MAX else None
                ),
                max_chat_id=(
                    max_chat_id if messenger_type == MessengerType.MAX else None
                ),
                role_chosen_at=role_chosen_at,
                last_role_reminder_at=None,
                telegram=telegram_username,
                admin=False,
                referral_code=referral_code,
            )
            await self.user_repo.save(new_user, session=session)
            return new_user

        return await with_optional_tx(self.transaction_manager, _run)

    async def _generate_unique_referral_code(
        self, session: object | None
    ) -> str:
        """Generate a unique referral code (for new users)."""
        for _ in range(REFERRAL_CODE_MAX_ATTEMPTS):
            code = "".join(
                secrets.choice(REFERRAL_CODE_ALPHABET)
                for _ in range(REFERRAL_CODE_LENGTH)
            )
            existing = await self.user_repo.get_by_referral_code(
                code, session=session
            )
            if existing is None:
                return code
        raise RuntimeError(
            "Failed to generate unique referral code after "
            f"{REFERRAL_CODE_MAX_ATTEMPTS} attempts"
        )

    async def get_user(
        self, external_id: str, messenger_type: MessengerType
    ) -> User | None:
        """Fetch a user by external id."""

        async def _run(session: object | None) -> User | None:
            return await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_user_id(
        self, external_id: str, messenger_type: MessengerType
    ) -> UUID | None:
        """Fetch a user id by external id."""

        async def _run(session: object | None) -> User | None:
            return await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )

        user = await with_optional_tx(self.transaction_manager, _run)
        return user.user_id if user else None

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Fetch a user by internal id."""

        async def _run(session: object | None) -> User | None:
            return await self.user_repo.get_by_id(user_id, session=session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def get_user_by_telegram(self, telegram: str) -> User | None:
        """Fetch a user by Telegram username (case-insensitive, @ stripped)."""
        normalized = (telegram or "").strip().lstrip("@").lower()
        if not normalized:
            return None

        async def _run(session: object | None) -> User | None:
            return await self.user_repo.get_by_telegram(
                normalized, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def update_status(self, user_id: UUID, status: UserStatus) -> User:
        """Update user status."""

        async def _run(session: object | None) -> tuple[User, User]:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError("User not found.")

            updated = replace(user, status=status)
            await self.user_repo.save(updated, session=session)
            return (updated, user)

        updated, user = await with_optional_tx(self.transaction_manager, _run)

        if status == UserStatus.BLOCKED:
            logger.warning(
                "User blocked",
                extra={
                    "user_id": str(user.user_id),
                    "telegram_id": user.telegram_id,
                    "max_id": user.max_id,
                    "username": user.username,
                    "previous_status": user.status.value,
                    "event_type": "user.blocked",
                },
            )

            if self.metrics_collector:
                self.metrics_collector.record_user_blocked(
                    user_id=str(user.user_id),
                    reason=f"Status changed from {user.status.value}",
                )

        return updated

    async def create_user(
        self,
        external_id: str,
        messenger_type: MessengerType = MessengerType.TELEGRAM,
        username: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        """Create a new user with specified parameters."""

        if username is None:
            username = f"user_{external_id}"

        async def _run(session: object | None) -> User:
            referral_code = await self._generate_unique_referral_code(session)
            new_user = User(
                user_id=uuid4(),
                messenger_type=messenger_type,
                username=username,
                status=status,
                issue_count=0,
                created_at=datetime.now(timezone.utc),
                telegram_id=(
                    external_id
                    if messenger_type == MessengerType.TELEGRAM
                    else None
                ),
                max_id=(
                    external_id if messenger_type == MessengerType.MAX else None
                ),
                role_chosen_at=None,
                last_role_reminder_at=None,
                telegram=None,
                admin=False,
                referral_code=referral_code,
            )
            await self.user_repo.save(new_user, session=session)
            return new_user

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_pending_role_reminders(
        self, reminder_cutoff: datetime
    ) -> list[User]:
        """List users who have not chosen a role and are due for a reminder."""

        async def _run(session: object | None) -> list[User]:
            return list(
                await self.user_repo.list_pending_role_reminders(
                    reminder_cutoff, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_admins(
        self, messenger_type: MessengerType | None = None
    ) -> list[User]:
        """List users with admin=True. Optionally filter by messenger_type."""

        async def _run(session: object | None) -> list[User]:
            return list(
                await self.user_repo.list_admins(
                    messenger_type=messenger_type, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def update_telegram(self, user: User, telegram: str | None) -> User:
        """Update user's telegram handle if it changed."""
        normalized = telegram.strip().lstrip("@") if telegram else None
        existing = user.telegram.strip().lstrip("@") if user.telegram else None
        if normalized == existing:
            return user

        async def _run(session: object | None) -> User:
            updated = replace(user, telegram=normalized)
            await self.user_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def set_country(
        self,
        external_id: str,
        messenger_type: MessengerType,
        country_code: str,
    ) -> User:
        """Set country for a user identified by external_id."""

        async def _run(session: object | None) -> User:
            user = await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )
            if user is None:
                raise UserNotFoundError("User not found.")
            updated = replace(user, country=country_code)
            await self.user_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def set_language(
        self,
        external_id: str,
        messenger_type: MessengerType,
        language_code: str,
    ) -> User:
        """Set language for a user identified by external_id."""

        async def _run(session: object | None) -> User:
            user = await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )
            if user is None:
                raise UserNotFoundError("User not found.")
            updated = replace(user, language=language_code)
            await self.user_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def update_last_role_reminder_at(self, user_id: UUID) -> None:
        """Set last_role_reminder_at to now for the user."""

        async def _run(session: object | None) -> None:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                return
            now = datetime.now(timezone.utc)
            updated = replace(user, last_role_reminder_at=now)
            await self.user_repo.save(updated, session=session)

        await with_optional_tx(self.transaction_manager, _run)

    async def link_max_account(
        self,
        max_id: str,
        instagram_url: str,
        username: str,
        max_chat_id: str | None = None,
    ) -> User | None:
        """Link a Max account to existing user by Instagram username.

        Extracts the username from *instagram_url* and looks up existing
        profiles by that username (case-insensitive).

        Returns the updated User if linked, None if no matching user found
        or user already has a different max_id.
        """

        async def _run(session: object | None) -> User | None:
            if self.blogger_profile_repo is None:
                return None
            ig_username = _extract_instagram_username(instagram_url)
            if not ig_username:
                return None
            profile = await self.blogger_profile_repo.get_by_instagram_username(
                ig_username, session=session
            )
            if profile is None:
                return None

            existing = await self.user_repo.get_by_id(
                profile.user_id, session=session
            )
            if existing is None:
                return None

            if existing.max_id is not None and existing.max_id != max_id:
                return None

            orphan = await self.user_repo.get_by_external(
                max_id, MessengerType.MAX, session=session
            )
            if orphan and orphan.user_id != existing.user_id:
                cleared = replace(orphan, max_id=None, max_chat_id=None)
                await self.user_repo.save(cleared, session=session)

            updated = replace(
                existing,
                max_id=max_id,
                max_chat_id=max_chat_id or existing.max_chat_id,
                username=username or existing.username,
            )
            await self.user_repo.save(updated, session=session)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)
