"""Service for user creation and lookup."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.ports import TransactionManager, UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserRoleService:
    """Manage user creation and lookup."""

    user_repo: UserRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
        role_chosen: bool = False,
        telegram_username: str | None = None,
    ) -> User:
        """Create or update a user.

        Args:
            external_id: External messenger id.
            messenger_type: Messenger type.
            username: Display username (name shown to advertisers).
            role_chosen: If True, set role_chosen_at to now when still unset.
            telegram_username: Telegram alias (@username), stored for admin only.
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
                updated = User(
                    user_id=existing.user_id,
                    external_id=existing.external_id,
                    messenger_type=existing.messenger_type,
                    username=username,
                    status=status,
                    issue_count=existing.issue_count,
                    created_at=existing.created_at,
                    role_chosen_at=role_chosen_at,
                    last_role_reminder_at=existing.last_role_reminder_at,
                    telegram=telegram,
                    admin=existing.admin,
                )
                await self.user_repo.save(updated, session=session)
                return updated

            status = UserStatus.ACTIVE
            role_chosen_at = now if role_chosen else None
            new_user = User(
                user_id=uuid4(),
                external_id=external_id,
                messenger_type=messenger_type,
                username=username,
                status=status,
                issue_count=0,
                created_at=now,
                role_chosen_at=role_chosen_at,
                last_role_reminder_at=None,
                telegram=telegram_username,
                admin=False,
            )
            await self.user_repo.save(new_user, session=session)
            return new_user

        return await with_optional_tx(self.transaction_manager, _run)

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

    async def update_status(self, user_id: UUID, status: UserStatus) -> User:
        """Update user status."""

        async def _run(session: object | None) -> tuple[User, User]:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                raise UserNotFoundError("User not found.")

            updated = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                role_chosen_at=user.role_chosen_at,
                last_role_reminder_at=user.last_role_reminder_at,
                telegram=user.telegram,
                admin=user.admin,
            )
            await self.user_repo.save(updated, session=session)
            return (updated, user)

        updated, user = await with_optional_tx(self.transaction_manager, _run)

        if status == UserStatus.BLOCKED:
            logger.warning(
                "User blocked",
                extra={
                    "user_id": str(user.user_id),
                    "external_id": user.external_id,
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

        new_user = User(
            user_id=uuid4(),
            external_id=external_id,
            messenger_type=messenger_type,
            username=username,
            status=status,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            role_chosen_at=None,
            last_role_reminder_at=None,
            telegram=None,
            admin=False,
        )

        async def _run(session: object | None) -> User:
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

    async def update_last_role_reminder_at(self, user_id: UUID) -> None:
        """Set last_role_reminder_at to now for the user."""

        async def _run(session: object | None) -> None:
            user = await self.user_repo.get_by_id(user_id, session=session)
            if user is None:
                return
            now = datetime.now(timezone.utc)
            updated = User(
                user_id=user.user_id,
                external_id=user.external_id,
                messenger_type=user.messenger_type,
                username=user.username,
                status=user.status,
                issue_count=user.issue_count,
                created_at=user.created_at,
                role_chosen_at=user.role_chosen_at,
                last_role_reminder_at=now,
                telegram=user.telegram,
                admin=user.admin,
            )
            await self.user_repo.save(updated, session=session)

        await with_optional_tx(self.transaction_manager, _run)
