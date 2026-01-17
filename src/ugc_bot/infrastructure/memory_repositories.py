"""In-memory repository implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from uuid import UUID

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    UserRepository,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import MessengerType


@dataclass
class InMemoryUserRepository(UserRepository):
    """In-memory implementation of user repository."""

    users: Dict[UUID, User] = field(default_factory=dict)
    external_index: Dict[Tuple[str, MessengerType], UUID] = field(default_factory=dict)

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Fetch a user by ID."""

        return self.users.get(user_id)

    def get_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        key = (external_id, messenger_type)
        user_id = self.external_index.get(key)
        return self.users.get(user_id) if user_id else None

    def save(self, user: User) -> None:
        """Persist a user in memory."""

        self.users[user.user_id] = user
        self.external_index[(user.external_id, user.messenger_type)] = user.user_id


@dataclass
class InMemoryBloggerProfileRepository(BloggerProfileRepository):
    """In-memory implementation of blogger profile repository."""

    profiles: Dict[UUID, BloggerProfile] = field(default_factory=dict)

    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        return self.profiles.get(user_id)

    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile in memory."""

        self.profiles[profile.user_id] = profile


@dataclass
class InMemoryAdvertiserProfileRepository(AdvertiserProfileRepository):
    """In-memory implementation of advertiser profile repository."""

    profiles: Dict[UUID, AdvertiserProfile] = field(default_factory=dict)

    def get_by_user_id(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        return self.profiles.get(user_id)

    def save(self, profile: AdvertiserProfile) -> None:
        """Persist advertiser profile in memory."""

        self.profiles[profile.user_id] = profile
