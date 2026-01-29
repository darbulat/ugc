"""Service for user creation and lookup."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID, uuid4

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


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
    ) -> User:
        """Create or update a user."""

        async def _run(session: object | None) -> User:
            existing = await self.user_repo.get_by_external(
                external_id, messenger_type, session=session
            )
            if existing:
                status = existing.status
                updated = User(
                    user_id=existing.user_id,
                    external_id=existing.external_id,
                    messenger_type=existing.messenger_type,
                    username=username,
                    status=status,
                    issue_count=existing.issue_count,
                    created_at=existing.created_at,
                )
                await self.user_repo.save(updated, session=session)
                return updated

            status = UserStatus.ACTIVE
            new_user = User(
                user_id=uuid4(),
                external_id=external_id,
                messenger_type=messenger_type,
                username=username,
                status=status,
                issue_count=0,
                created_at=datetime.now(timezone.utc),
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
        )

        async def _run(session: object | None) -> User:
            await self.user_repo.save(new_user, session=session)
            return new_user

        return await with_optional_tx(self.transaction_manager, _run)
