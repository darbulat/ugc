"""Unit tests for UserRoleService.update_telegram."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


def _make_user(telegram: str | None = None) -> User:
    return User(
        user_id=uuid4(),
        external_id=str(uuid4()),
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram=telegram,
    )


def _make_service(
    user_repo: InMemoryUserRepository | None = None,
) -> tuple[UserRoleService, InMemoryUserRepository]:
    repo = user_repo or InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    return service, repo


@pytest.mark.asyncio
async def test_update_telegram_saves_when_changed() -> None:
    service, repo = _make_service()
    user = _make_user(telegram="old_handle")
    await repo.save(user)

    result = await service.update_telegram(user, "new_handle")

    assert result.telegram == "new_handle"
    saved = await repo.get_by_id(user.user_id)
    assert saved is not None
    assert saved.telegram == "new_handle"


@pytest.mark.asyncio
async def test_update_telegram_no_save_when_unchanged() -> None:
    service, repo = _make_service()
    user = _make_user(telegram="same_handle")
    await repo.save(user)

    result = await service.update_telegram(user, "same_handle")

    assert result is user  # exact same object, no replace


@pytest.mark.asyncio
async def test_update_telegram_strips_at_prefix() -> None:
    service, repo = _make_service()
    user = _make_user(telegram=None)
    await repo.save(user)

    result = await service.update_telegram(user, "@myhandle")

    assert result.telegram == "myhandle"
    saved = await repo.get_by_id(user.user_id)
    assert saved is not None
    assert saved.telegram == "myhandle"


@pytest.mark.asyncio
async def test_update_telegram_no_save_when_at_prefix_matches() -> None:
    service, repo = _make_service()
    user = _make_user(telegram="myhandle")
    await repo.save(user)

    result = await service.update_telegram(user, "@myhandle")

    assert result is user


@pytest.mark.asyncio
async def test_update_telegram_sets_none_when_empty() -> None:
    service, repo = _make_service()
    user = _make_user(telegram="old_handle")
    await repo.save(user)

    result = await service.update_telegram(user, None)

    assert result.telegram is None
    saved = await repo.get_by_id(user.user_id)
    assert saved is not None
    assert saved.telegram is None


@pytest.mark.asyncio
async def test_update_telegram_no_save_when_both_none() -> None:
    service, repo = _make_service()
    user = _make_user(telegram=None)
    await repo.save(user)

    result = await service.update_telegram(user, None)

    assert result is user


@pytest.mark.asyncio
async def test_update_telegram_strips_whitespace() -> None:
    service, repo = _make_service()
    user = _make_user(telegram=None)
    await repo.save(user)

    result = await service.update_telegram(user, "  @handle  ")

    assert result.telegram == "handle"
