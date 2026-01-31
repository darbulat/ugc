"""Tests for blogger registration service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus, WorkFormat
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)


async def _seed_user(repo: InMemoryUserRepository) -> UUID:
    """Seed a user in the in-memory repo."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        external_id="555",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(user)
    return user.user_id


@pytest.mark.asyncio
async def test_register_blogger_success() -> None:
    """Register a blogger with valid data."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
    )

    assert profile.user_id == user_id
    assert profile.confirmed is False


@pytest.mark.asyncio
async def test_register_blogger_duplicate_instagram_url() -> None:
    """Reject registration with duplicate Instagram URL."""
    from ugc_bot.domain.entities import BloggerProfile
    from datetime import datetime, timezone

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    # Create first user and profile
    user1 = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="user1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user1)
    existing_profile = BloggerProfile(
        user_id=user1.user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(existing_profile)

    # Create second user
    user2 = User(
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="user2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user2)

    # Try to register with same Instagram URL
    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user2.user_id,
            instagram_url="https://instagram.com/test_user",
            city="SPB",
            topics={"selected": ["beauty"]},
            audience_gender=AudienceGender.FEMALE,
            audience_age_min=20,
            audience_age_max=30,
            audience_geo="SPB",
            price=2000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )

    assert "уже зарегистрирован" in str(exc_info.value)


@pytest.mark.asyncio
async def test_register_blogger_empty_instagram() -> None:
    """Reject empty Instagram URL."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )


@pytest.mark.asyncio
async def test_register_blogger_missing_user() -> None:
    """Fail when user does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.register_blogger(
            user_id=UUID("00000000-0000-0000-0000-000000000003"),
            instagram_url="https://instagram.com/test_user",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )


@pytest.mark.asyncio
async def test_register_blogger_invalid_age() -> None:
    """Reject invalid audience age range."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=40,
            audience_age_max=30,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )


@pytest.mark.asyncio
async def test_register_blogger_invalid_geo_and_price() -> None:
    """Reject missing geo and invalid price."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )


@pytest.mark.asyncio
async def test_register_blogger_non_positive_age_is_rejected() -> None:
    """Reject non-positive audience ages."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=0,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
        )


@pytest.mark.asyncio
async def test_register_blogger_records_metrics_when_enabled() -> None:
    """Record metrics when collector is provided."""

    from unittest.mock import Mock

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    metrics = Mock()

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        metrics_collector=metrics,
    )

    await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
    )

    metrics.record_blogger_registration.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_register_blogger_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for register_blogger."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
    )
    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/tm_user",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
    )
    assert profile.user_id == user_id
    assert profile.confirmed is False


@pytest.mark.asyncio
async def test_get_profile_by_instagram_url_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover transaction_manager path for get_profile_by_instagram_url."""
    from ugc_bot.domain.entities import BloggerProfile

    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = UUID("00000000-0000-0000-0000-000000000099")
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/with_tm",
        confirmed=False,
        city="Moscow",
        topics={"selected": []},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(profile)
    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
    )
    result = await service.get_profile_by_instagram_url("https://instagram.com/with_tm")
    assert result is not None
    assert result.instagram_url == "https://instagram.com/with_tm"
