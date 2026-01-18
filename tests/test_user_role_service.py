"""Tests for the user role service."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


def test_set_role_creates_new_user() -> None:
    """Ensure a new user is created when none exists."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    user = service.set_role(
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        role=UserRole.BLOGGER,
    )

    assert user.external_id == "123"
    assert user.role == UserRole.BLOGGER
    assert repo.get_by_id(user.user_id) is not None


def test_set_role_new_advertiser_status() -> None:
    """New advertiser should be marked as NEW."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    user = service.set_role(
        external_id="321",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
    )

    assert user.status == UserStatus.NEW


def test_set_role_updates_existing_user() -> None:
    """Ensure existing users are updated."""

    repo = InMemoryUserRepository()
    existing = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(existing)

    service = UserRoleService(user_repo=repo)
    updated = service.set_role(
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice-updated",
        role=UserRole.ADVERTISER,
    )

    assert updated.user_id == existing.user_id
    assert updated.role == UserRole.ADVERTISER
    assert updated.username == "alice-updated"


def test_get_user_id() -> None:
    """Return user id when exists."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    created = service.set_role(
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="john",
        role=UserRole.BLOGGER,
    )

    assert service.get_user_id("777", MessengerType.TELEGRAM) == created.user_id
    assert service.get_user_id("999", MessengerType.TELEGRAM) is None
