"""Tests for advertiser registration service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryUserRepository,
)


def _seed_user(repo: InMemoryUserRepository) -> UUID:
    """Seed a user in the in-memory repo."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000120"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(user)
    return user.user_id


def test_register_advertiser_success() -> None:
    """Register an advertiser with valid data."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    profile = service.register_advertiser(user_id=user_id, contact="@contact")
    assert profile.user_id == user_id
    assert profile.contact == "@contact"


def test_register_advertiser_missing_user() -> None:
    """Fail when user does not exist."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.register_advertiser(
            user_id=UUID("00000000-0000-0000-0000-000000000121"),
            contact="@contact",
        )


def test_register_advertiser_empty_contact() -> None:
    """Fail when contact is empty."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    with pytest.raises(AdvertiserRegistrationError):
        service.register_advertiser(user_id=user_id, contact=" ")
