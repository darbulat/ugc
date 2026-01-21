"""Service for user creation and lookup."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus


@dataclass(slots=True)
class UserRoleService:
    """Manage user creation and lookup."""

    user_repo: UserRepository

    def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
    ) -> User:
        """Create or update a user."""

        existing = self.user_repo.get_by_external(external_id, messenger_type)
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
            self.user_repo.save(updated)
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
        self.user_repo.save(new_user)
        return new_user

    def get_user(self, external_id: str, messenger_type: MessengerType) -> User | None:
        """Fetch a user by external id."""

        return self.user_repo.get_by_external(external_id, messenger_type)

    def get_user_id(
        self, external_id: str, messenger_type: MessengerType
    ) -> UUID | None:
        """Fetch a user id by external id."""

        user = self.user_repo.get_by_external(external_id, messenger_type)
        return user.user_id if user else None

    def get_user_by_id(self, user_id: UUID) -> User | None:
        """Fetch a user by internal id."""

        return self.user_repo.get_by_id(user_id)

    def update_status(self, user_id: UUID, status: UserStatus) -> User:
        """Update user status."""

        user = self.user_repo.get_by_id(user_id)
        if user is None:
            raise ValueError("User not found.")

        updated = User(
            user_id=user.user_id,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            status=status,
            issue_count=user.issue_count,
            created_at=user.created_at,
        )
        self.user_repo.save(updated)
        return updated

    def create_user(
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
        self.user_repo.save(new_user)
        return new_user
