"""Tests for blogger registration service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)


def _seed_user(repo: InMemoryUserRepository) -> UUID:
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
    repo.save(user)
    return user.user_id


def test_register_blogger_success() -> None:
    """Register a blogger with valid data."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    profile = service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
    )

    assert profile.user_id == user_id
    assert profile.confirmed is False


def test_register_blogger_duplicate_instagram_url() -> None:
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
    user_repo.save(user1)
    existing_profile = BloggerProfile(
        user_id=user1.user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    blogger_repo.save(existing_profile)

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
    user_repo.save(user2)

    # Try to register with same Instagram URL
    with pytest.raises(BloggerRegistrationError) as exc_info:
        service.register_blogger(
            user_id=user2.user_id,
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["beauty"]},
            audience_gender=AudienceGender.FEMALE,
            audience_age_min=20,
            audience_age_max=30,
            audience_geo="SPB",
            price=2000.0,
        )

    assert "уже зарегистрирован" in str(exc_info.value)


def test_register_blogger_empty_instagram() -> None:
    """Reject empty Instagram URL."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        service.register_blogger(
            user_id=user_id,
            instagram_url="",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
        )


def test_register_blogger_missing_user() -> None:
    """Fail when user does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.register_blogger(
            user_id=UUID("00000000-0000-0000-0000-000000000003"),
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
        )


def test_register_blogger_invalid_age() -> None:
    """Reject invalid audience age range."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=40,
            audience_age_max=30,
            audience_geo="Moscow",
            price=1500.0,
        )


def test_register_blogger_invalid_geo_and_price() -> None:
    """Reject missing geo and invalid price."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = _seed_user(user_repo)

    service = BloggerRegistrationService(user_repo=user_repo, blogger_repo=blogger_repo)

    with pytest.raises(BloggerRegistrationError):
        service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="",
            price=1500.0,
        )

    with pytest.raises(BloggerRegistrationError):
        service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test_user",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=0.0,
        )
