"""Service for user role management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus


@dataclass(slots=True)
class UserRoleService:
    """Manage user role assignment."""

    user_repo: UserRepository

    def set_role(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
        role: UserRole,
    ) -> User:
        """Create or update a user with the selected role."""

        existing = self.user_repo.get_by_external(external_id, messenger_type)
        if existing:
            status = existing.status
            if (
                role in {UserRole.ADVERTISER, UserRole.BOTH}
                and existing.role not in {UserRole.ADVERTISER, UserRole.BOTH}
                and existing.status == UserStatus.ACTIVE
            ):
                status = UserStatus.NEW
            updated = User(
                user_id=existing.user_id,
                external_id=existing.external_id,
                messenger_type=existing.messenger_type,
                username=username,
                role=role,
                status=status,
                issue_count=existing.issue_count,
                created_at=existing.created_at,
            )
            self.user_repo.save(updated)
            return updated

        status = (
            UserStatus.NEW
            if role in {UserRole.ADVERTISER, UserRole.BOTH}
            else UserStatus.ACTIVE
        )
        new_user = User(
            user_id=uuid4(),
            external_id=external_id,
            messenger_type=messenger_type,
            username=username,
            role=role,
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
