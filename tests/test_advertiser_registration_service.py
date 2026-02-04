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
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryUserRepository,
)


async def _seed_user(repo: InMemoryUserRepository) -> UUID:
    """Seed a user in the in-memory repo."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000120"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(user)
    return user.user_id


@pytest.mark.asyncio
async def test_register_advertiser_success() -> None:
    """Register an advertiser with valid data."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    profile = await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="Test Brand",
        city="Казань",
        company_activity="Продажа одежды",
    )
    assert profile.user_id == user_id
    assert profile.phone == "@contact"
    assert profile.brand == "Test Brand"
    assert profile.city == "Казань"
    assert profile.company_activity == "Продажа одежды"


@pytest.mark.asyncio
async def test_register_advertiser_missing_user() -> None:
    """Fail when user does not exist."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.register_advertiser(
            user_id=UUID("00000000-0000-0000-0000-000000000121"),
            phone="@contact",
            brand="B",
        )


@pytest.mark.asyncio
async def test_register_advertiser_empty_phone() -> None:
    """Fail when phone is empty."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    with pytest.raises(AdvertiserRegistrationError):
        await service.register_advertiser(user_id=user_id, phone=" ", brand="B")


@pytest.mark.asyncio
async def test_register_advertiser_empty_brand() -> None:
    """Fail when brand is empty."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    with pytest.raises(AdvertiserRegistrationError):
        await service.register_advertiser(user_id=user_id, phone="+7900", brand=" ")


@pytest.mark.asyncio
async def test_register_advertiser_records_metrics_when_enabled() -> None:
    """Record metrics when collector is provided."""

    from unittest.mock import Mock

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    metrics = Mock()

    service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        metrics_collector=metrics,
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="B",
    )

    metrics.record_advertiser_registration.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_get_profile_returns_saved_profile() -> None:
    """Return profile from repository."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    created = await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="B",
    )
    loaded = await service.get_profile(user_id)

    assert loaded == created


@pytest.mark.asyncio
async def test_register_advertiser_with_transaction_manager(fake_tm: object) -> None:
    """Cover transaction_manager path for register_advertiser and get_profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=fake_tm,
    )
    profile = await service.register_advertiser(
        user_id=user_id,
        phone="@tm_contact",
        brand="Brand",
    )
    assert profile.phone == "@tm_contact"
    loaded = await service.get_profile(user_id)
    assert loaded == profile
