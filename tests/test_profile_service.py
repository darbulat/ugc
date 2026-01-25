"""Tests for profile service."""

from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


def test_get_user_by_external() -> None:
    """Get user by external id and messenger type."""

    user_repo = InMemoryUserRepository()
    service = ProfileService(user_repo=user_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000200"),
        external_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="test_user",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url="https://instagram.com/test_user",
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
    user_repo.save(user)

    found_user = service.get_user_by_external("100", MessengerType.TELEGRAM)
    assert found_user is not None
    assert found_user.user_id == user.user_id
    assert found_user.external_id == "100"

    # Non-existent user
    assert service.get_user_by_external("999", MessengerType.TELEGRAM) is None


def test_get_blogger_profile() -> None:
    """Get blogger profile by user id."""

    user_repo = InMemoryUserRepository()
    service = ProfileService(user_repo=user_repo)

    user_id = UUID("00000000-0000-0000-0000-000000000201")
    profile = User(
        user_id=user_id,
        external_id="200",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url="https://instagram.com/test",
        confirmed=False,
        topics={"selected": ["tech"]},
        audience_gender=None,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        contact=None,
        profile_updated_at=datetime.now(timezone.utc),
    )
    user_repo.save(profile)

    found_profile = service.get_blogger_profile(user_id)
    assert found_profile is not None
    assert found_profile.user_id == user_id

    # Non-existent profile
    assert (
        service.get_blogger_profile(UUID("00000000-0000-0000-0000-000000000999"))
        is None
    )


def test_get_advertiser_profile() -> None:
    """Get advertiser profile by user id."""

    user_repo = InMemoryUserRepository()
    service = ProfileService(user_repo=user_repo)

    user_id = UUID("00000000-0000-0000-0000-000000000202")
    profile = User(
        user_id=user_id,
        external_id="300",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        contact="contact@example.com",
        instagram_url="https://instagram.com/advertiser",
        confirmed=True,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        profile_updated_at=datetime.now(timezone.utc),
    )
    user_repo.save(profile)

    found_profile = service.get_advertiser_profile(user_id)
    assert found_profile is not None
    assert found_profile.user_id == user_id

    # Non-existent profile
    assert (
        service.get_advertiser_profile(UUID("00000000-0000-0000-0000-000000000999"))
        is None
    )
