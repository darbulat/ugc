"""Service for user creation and lookup."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.ports import UserRepository
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserRoleService:
    """Manage user creation and lookup."""

    user_repo: UserRepository
    metrics_collector: Optional[Any] = None

    def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
        role: UserRole | None = None,
    ) -> User:
        """Create or update a user."""

        existing = self.user_repo.get_by_external(external_id, messenger_type)
        if existing:
            status = existing.status
            updated_role = _merge_roles(existing.role, role) if role else existing.role
            updated = User(
                user_id=existing.user_id,
                external_id=existing.external_id,
                messenger_type=existing.messenger_type,
                username=username,
                role=updated_role,
                status=status,
                issue_count=existing.issue_count,
                created_at=existing.created_at,
                instagram_url=existing.instagram_url,
                confirmed=existing.confirmed,
                topics=existing.topics,
                audience_gender=existing.audience_gender,
                audience_age_min=existing.audience_age_min,
                audience_age_max=existing.audience_age_max,
                audience_geo=existing.audience_geo,
                price=existing.price,
                contact=existing.contact,
                profile_updated_at=existing.profile_updated_at,
            )
            self.user_repo.save(updated)
            return updated

        status = UserStatus.ACTIVE
        resolved_role = role or UserRole.BLOGGER
        new_user = User(
            user_id=uuid4(),
            external_id=external_id,
            messenger_type=messenger_type,
            username=username,
            role=resolved_role,
            status=status,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            instagram_url=None,
            confirmed=False,
            topics=None,
            audience_gender=None,
            audience_age_min=None,
            audience_age_max=None,
            audience_geo=None,
            price=None,
            contact=None,
            profile_updated_at=None,
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
            role=user.role,
            status=status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            instagram_url=user.instagram_url,
            confirmed=user.confirmed,
            topics=user.topics,
            audience_gender=user.audience_gender,
            audience_age_min=user.audience_age_min,
            audience_age_max=user.audience_age_max,
            audience_geo=user.audience_geo,
            price=user.price,
            contact=user.contact,
            profile_updated_at=user.profile_updated_at,
        )
        self.user_repo.save(updated)

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

    def create_user(
        self,
        external_id: str,
        messenger_type: MessengerType = MessengerType.TELEGRAM,
        username: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        role: UserRole = UserRole.BLOGGER,
    ) -> User:
        """Create a new user with specified parameters."""

        if username is None:
            username = f"user_{external_id}"

        new_user = User(
            user_id=uuid4(),
            external_id=external_id,
            messenger_type=messenger_type,
            username=username,
            role=role,
            status=status,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            instagram_url=None,
            confirmed=False,
            topics=None,
            audience_gender=None,
            audience_age_min=None,
            audience_age_max=None,
            audience_geo=None,
            price=None,
            contact=None,
            profile_updated_at=None,
        )
        self.user_repo.save(new_user)
        return new_user


def _merge_roles(existing: UserRole, incoming: UserRole) -> UserRole:
    """Merge role updates into a single user role."""

    if existing == incoming:
        return existing
    if existing == UserRole.BOTH or incoming == UserRole.BOTH:
        return UserRole.BOTH
    return UserRole.BOTH
