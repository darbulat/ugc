"""Tests for the user role service."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

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

    assert (
        await service.get_user_id("777", MessengerType.TELEGRAM)
        == created.user_id
    )
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
    assert (
        await service.get_user_id("nonexistent", MessengerType.TELEGRAM) is None
    )


@pytest.mark.asyncio
async def test_get_user_and_get_by_id_with_transaction_manager(
    fake_tm: object,
) -> None:
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


@pytest.mark.asyncio
async def test_set_user_role_chosen_sets_role_chosen_at() -> None:
    """set_user with role_chosen=True sets role_chosen_at."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    user = await service.set_user(
        external_id="rc-1",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        role_chosen=True,
    )
    assert user.role_chosen_at is not None


@pytest.mark.asyncio
async def test_list_pending_role_reminders_returns_users_without_role_chosen(
    fake_tm: object,
) -> None:
    """list_pending_role_reminders returns users with role_chosen_at None."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    await service.set_user(
        external_id="p1",
        messenger_type=MessengerType.TELEGRAM,
        username="u1",
        role_chosen=False,
    )
    await service.set_user(
        external_id="p2",
        messenger_type=MessengerType.TELEGRAM,
        username="u2",
        role_chosen=True,
    )
    cutoff = datetime.now(timezone.utc)
    pending = await service.list_pending_role_reminders(cutoff)
    external_ids = {u.external_id for u in pending}
    assert "p1" in external_ids
    assert "p2" not in external_ids


@pytest.mark.asyncio
async def test_user_repo_iter_all() -> None:
    """InMemoryUserRepository.iter_all returns all users."""

    repo = InMemoryUserRepository()
    await repo.save(
        User(
            user_id=uuid4(),
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u1",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    users = list(await repo.iter_all())
    assert len(users) == 1
    assert users[0].username == "u1"


@pytest.mark.asyncio
async def test_update_last_role_reminder_at(fake_tm: object) -> None:
    """update_last_role_reminder_at sets last_role_reminder_at."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    user = await service.set_user(
        external_id="rem-1",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        role_chosen=False,
    )
    await service.update_last_role_reminder_at(user.user_id)
    updated = await service.get_user_by_id(user.user_id)
    assert updated is not None
    assert updated.last_role_reminder_at is not None


@pytest.mark.asyncio
async def test_update_last_role_reminder_at_nonexistent_user(
    fake_tm: object,
) -> None:
    """update_last_role_reminder_at does nothing when user not found."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo, transaction_manager=fake_tm)
    await service.update_last_role_reminder_at(
        UUID("00000000-0000-0000-0000-000000000999")
    )


@pytest.mark.asyncio
async def test_create_user_with_default_username() -> None:
    """create_user uses default username when username is None."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    user = await service.create_user(
        external_id="ext-42",
        messenger_type=MessengerType.TELEGRAM,
        username=None,
    )
    assert user.username == "user_ext-42"


@pytest.mark.asyncio
async def test_update_status_records_metrics_when_blocked() -> None:
    """update_status calls metrics.record_user_blocked when status BLOCKED."""

    from unittest.mock import MagicMock

    repo = InMemoryUserRepository()
    metrics = MagicMock()
    metrics.record_user_blocked = MagicMock()
    service = UserRoleService(user_repo=repo, metrics_collector=metrics)
    user = await service.set_user(
        external_id="m1",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
    )
    await service.update_status(user.user_id, UserStatus.BLOCKED)
    metrics.record_user_blocked.assert_called_once()
