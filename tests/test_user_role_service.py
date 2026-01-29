"""Tests for the user role service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


@pytest.mark.asyncio
async def test_set_user_creates_new_user() -> None:
    """Ensure a new user is created when none exists."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    user = await service.set_user(
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )

    assert user.external_id == "123"
    assert await repo.get_by_id(user.user_id) is not None


@pytest.mark.asyncio
async def test_set_user_updates_existing_user() -> None:
    """Ensure existing users are updated."""

    repo = InMemoryUserRepository()
    existing = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(existing)

    service = UserRoleService(user_repo=repo)
    updated = await service.set_user(
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="alice-updated",
    )

    assert updated.user_id == existing.user_id
    assert updated.username == "alice-updated"


@pytest.mark.asyncio
async def test_get_user_id() -> None:
    """Return user id when exists."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    created = await service.set_user(
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="john",
    )

    assert await service.get_user_id("777", MessengerType.TELEGRAM) == created.user_id
    assert await service.get_user_id("999", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_update_status() -> None:
    """Update user status."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    user = await service.set_user(
        external_id="888",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
    )

    updated = await service.update_status(user.user_id, UserStatus.BLOCKED)

    assert updated.status == UserStatus.BLOCKED
    assert updated.user_id == user.user_id
    assert updated.username == user.username
    found = await repo.get_by_id(user.user_id)
    assert found is not None
    assert found.status == UserStatus.BLOCKED


@pytest.mark.asyncio
async def test_update_status_not_found() -> None:
    """Raise error when updating status of non-existent user."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    with pytest.raises(UserNotFoundError, match="not found"):
        await service.update_status(
            UUID("00000000-0000-0000-0000-000000000999"), UserStatus.BLOCKED
        )


@pytest.mark.asyncio
async def test_set_user_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path: set_user creates and updates user."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    user = await service.set_user(
        external_id="tm-123",
        messenger_type=MessengerType.TELEGRAM,
        username="tm_user",
    )
    assert user.external_id == "tm-123"
    updated = await service.set_user(
        external_id="tm-123",
        messenger_type=MessengerType.TELEGRAM,
        username="tm_user_updated",
    )
    assert updated.username == "tm_user_updated"


@pytest.mark.asyncio
async def test_get_user_id_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for get_user_id."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    await service.set_user(
        external_id="tid-1", messenger_type=MessengerType.TELEGRAM, username="u"
    )
    uid = await service.get_user_id("tid-1", MessengerType.TELEGRAM)
    assert uid is not None
    assert await service.get_user_id("nonexistent", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_get_user_and_get_by_id_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for get_user and get_user_by_id."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    created = await service.set_user(
        external_id="gid-1", messenger_type=MessengerType.TELEGRAM, username="u"
    )
    found = await service.get_user("gid-1", MessengerType.TELEGRAM)
    assert found is not None and found.user_id == created.user_id
    by_id = await service.get_user_by_id(created.user_id)
    assert by_id is not None and by_id.user_id == created.user_id


@pytest.mark.asyncio
async def test_update_status_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for update_status."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    user = await service.set_user(
        external_id="st-1", messenger_type=MessengerType.TELEGRAM, username="u"
    )
    updated = await service.update_status(user.user_id, UserStatus.BLOCKED)
    assert updated.status == UserStatus.BLOCKED
