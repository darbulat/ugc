"""Tests for the user role service."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.errors import UserNotFoundError
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)


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

    assert user.telegram_id == "123"
    assert await repo.get_by_id(user.user_id) is not None


@pytest.mark.asyncio
async def test_set_user_updates_existing_user() -> None:
    """Ensure existing users are updated."""

    repo = InMemoryUserRepository()
    existing = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        telegram_id="123",
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
        max_chat_id="max-chat-99",
    )

    assert updated.user_id == existing.user_id
    assert updated.username == "alice-updated"
    assert updated.max_chat_id == "max-chat-99"


@pytest.mark.asyncio
async def test_set_user_preserves_country() -> None:
    """Regression: set_user must not overwrite user.country with None."""

    repo = InMemoryUserRepository()
    existing = User(
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        telegram_id="cnt-1",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="kz",
    )
    await repo.save(existing)
    service = UserRoleService(user_repo=repo)
    await service.set_user(
        external_id="cnt-1",
        messenger_type=MessengerType.TELEGRAM,
        username="bob-updated",
    )
    found = await repo.get_by_id(existing.user_id)
    assert found is not None
    assert found.country == "kz"


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
async def test_update_status_preserves_optional_fields() -> None:
    """Regression: update_status must not drop optional user fields."""

    repo = InMemoryUserRepository()
    now = datetime.now(timezone.utc)
    user = User(
        user_id=uuid4(),
        telegram_id="opt-1",
        max_id="max-1",
        max_chat_id="max-chat-1",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
        referral_code="ref123",
        referral_payout_rate=Decimal("0.10"),
        country="kz",
    )
    await repo.save(user)
    service = UserRoleService(user_repo=repo)
    await service.update_status(user.user_id, UserStatus.PAUSE)
    found = await repo.get_by_id(user.user_id)
    assert found is not None
    assert found.status == UserStatus.PAUSE
    assert found.telegram_id == "opt-1"
    assert found.max_id == "max-1"
    assert found.max_chat_id == "max-chat-1"
    assert found.referral_code == "ref123"
    assert found.referral_payout_rate == Decimal("0.10")
    assert found.country == "kz"


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
    assert user.telegram_id == "tm-123"
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
async def test_get_user_by_telegram() -> None:
    """get_user_by_telegram finds user by telegram (normalizes @ and case)."""
    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)

    created = await service.set_user(
        external_id="tg-1",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        telegram_username="AliceBot",
    )

    found = await service.get_user_by_telegram("AliceBot")
    assert found is not None and found.user_id == created.user_id
    found2 = await service.get_user_by_telegram("@alicebot")
    assert found2 is not None and found2.user_id == created.user_id
    assert await service.get_user_by_telegram("") is None
    assert await service.get_user_by_telegram("nonexistent") is None


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
    telegram_ids = {u.telegram_id for u in pending}
    assert "p1" in telegram_ids
    assert "p2" not in telegram_ids


@pytest.mark.asyncio
async def test_user_repo_iter_all() -> None:
    """InMemoryUserRepository.iter_all returns all users."""

    repo = InMemoryUserRepository()
    await repo.save(
        User(
            user_id=uuid4(),
            telegram_id="1",
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
async def test_update_last_role_reminder_at_preserves_optional_fields() -> None:
    """Regression: must not drop optional User fields on reminder update."""

    repo = InMemoryUserRepository()
    now = datetime.now(timezone.utc)
    user = User(
        user_id=uuid4(),
        telegram_id="rem-opt",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
        referral_code="remref",
        country="kz",
    )
    await repo.save(user)
    service = UserRoleService(user_repo=repo)
    await service.update_last_role_reminder_at(user.user_id)
    found = await repo.get_by_id(user.user_id)
    assert found is not None
    assert found.last_role_reminder_at is not None
    assert found.referral_code == "remref"
    assert found.country == "kz"


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


@pytest.mark.asyncio
async def test_set_user_raises_when_referral_code_collision() -> None:
    """When all referral code attempts collide, set_user raises RuntimeError."""
    mock_repo = MagicMock()
    mock_repo.get_by_external = AsyncMock(return_value=None)
    mock_repo.get_by_referral_code = AsyncMock(
        return_value=User(
            user_id=uuid4(),
            telegram_id="other",
            messenger_type=MessengerType.TELEGRAM,
            username="other",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
            referral_code="taken",
        )
    )
    mock_repo.save = AsyncMock()
    service = UserRoleService(user_repo=mock_repo, transaction_manager=None)
    with pytest.raises(RuntimeError, match="unique referral code"):
        await service.set_user(
            external_id="new_user",
            messenger_type=MessengerType.TELEGRAM,
            username="new",
        )


@pytest.mark.asyncio
async def test_set_country_updates_user() -> None:
    """set_country stores country on the user."""
    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    user = await service.set_user(
        external_id="c-1",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )
    assert user.country is None
    updated = await service.set_country(
        external_id="c-1",
        messenger_type=MessengerType.TELEGRAM,
        country_code="ru",
    )
    assert updated.country == "ru"
    stored = await repo.get_by_id(user.user_id)
    assert stored is not None
    assert stored.country == "ru"


@pytest.mark.asyncio()
async def test_set_language_updates_user():
    """set_language() persists user.language."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="tester",
        role_chosen=False,
    )
    await service.set_language(
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        language_code="en",
    )
    result = await service.get_user("111", MessengerType.TELEGRAM)
    assert result is not None
    assert result.language == "en"


@pytest.mark.asyncio
async def test_set_country_not_found() -> None:
    """set_country raises UserNotFoundError when user does not exist."""
    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    with pytest.raises(UserNotFoundError):
        await service.set_country(
            external_id="missing",
            messenger_type=MessengerType.TELEGRAM,
            country_code="ru",
        )


@pytest.mark.asyncio
async def test_link_max_account_success() -> None:
    """Link max_id to existing Telegram user, clearing orphan Max user."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    existing_user = User(
        user_id=uuid4(),
        telegram_id="tg_111",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(existing_user)

    orphan_user = User(
        user_id=uuid4(),
        max_id="max_222",
        max_chat_id="chat_222",
        messenger_type=MessengerType.MAX,
        username="orphan",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(orphan_user)

    await blogger_repo.save(
        BloggerProfile(
            user_id=existing_user.user_id,
            instagram_url="https://instagram.com/alice",
            confirmed=True,
            city="Moscow",
            topics={},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=65,
            audience_geo="RU",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    # URL differs from stored one (trailing slash, www) — match by username
    linked = await service.link_max_account(
        max_id="max_222",
        instagram_url="https://www.instagram.com/Alice/",
        username="alice_max",
        max_chat_id="chat_222",
    )

    assert linked is not None
    assert linked.user_id == existing_user.user_id
    assert linked.max_id == "max_222"
    assert linked.max_chat_id == "chat_222"
    assert linked.telegram_id == "tg_111"
    assert linked.messenger_type == MessengerType.TELEGRAM
    assert linked.username == "alice_max"

    deleted_orphan = await user_repo.get_by_id(orphan_user.user_id)
    assert deleted_orphan is None


@pytest.mark.asyncio
async def test_link_max_account_not_found() -> None:
    """Return None when instagram_url not in DB."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_333",
        instagram_url="https://instagram.com/unknown",
        username="nobody",
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_max_account_profile_user_missing() -> None:
    """Return None when profile exists but referenced user is gone."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    missing_uid = uuid4()
    await blogger_repo.save(
        BloggerProfile(
            user_id=missing_uid,
            instagram_url="https://instagram.com/ghost",
            confirmed=True,
            city="Moscow",
            topics={},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=65,
            audience_geo="RU",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )
    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_999",
        instagram_url="https://instagram.com/ghost",
        username="ghost",
    )
    assert result is None


@pytest.mark.asyncio
async def test_link_max_account_already_has_max_id() -> None:
    """Return None when user already has a different max_id."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    existing_user = User(
        user_id=uuid4(),
        telegram_id="tg_111",
        max_id="max_existing",
        messenger_type=MessengerType.MAX,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(existing_user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=existing_user.user_id,
            instagram_url="https://instagram.com/alice",
            confirmed=True,
            city="Moscow",
            topics={},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=65,
            audience_geo="RU",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_new",
        instagram_url="https://instagram.com/alice",
        username="alice_max",
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_max_account_idempotent() -> None:
    """Re-linking with the same max_id succeeds (idempotent)."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    existing_user = User(
        user_id=uuid4(),
        telegram_id="tg_111",
        max_id="max_222",
        messenger_type=MessengerType.MAX,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(existing_user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=existing_user.user_id,
            instagram_url="https://instagram.com/alice",
            confirmed=True,
            city="Moscow",
            topics={},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=65,
            audience_geo="RU",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )
    )

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_222",
        instagram_url="https://instagram.com/alice",
        username="alice_updated",
    )

    assert result is not None
    assert result.max_id == "max_222"
    assert result.username == "alice_updated"


@pytest.mark.asyncio
async def test_link_max_account_no_blogger_repo() -> None:
    """Return None when blogger_profile_repo is not configured."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    result = await service.link_max_account(
        max_id="max_1",
        instagram_url="https://instagram.com/alice",
        username="alice",
    )
    assert result is None


@pytest.mark.asyncio
async def test_link_max_account_invalid_url() -> None:
    """Return None when instagram_url has no valid username."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    service = UserRoleService(
        user_repo=user_repo, blogger_profile_repo=blogger_repo
    )
    result = await service.link_max_account(
        max_id="max_1",
        instagram_url="not-a-valid-url",
        username="alice",
    )
    assert result is None
