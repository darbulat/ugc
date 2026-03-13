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
from ugc_bot.domain.entities import AdvertiserProfile, User
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
        await service.register_advertiser(
            user_id=user_id, phone="+7900", brand=" "
        )


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
async def test_register_advertiser_referral_binding_called() -> None:
    """create_binding_from_pending is called when referral_service is set."""

    from unittest.mock import AsyncMock, Mock

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    mock_referral = Mock()
    mock_referral.create_binding_from_pending = AsyncMock(return_value=None)

    service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        referral_service=mock_referral,
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="B",
    )

    mock_referral.create_binding_from_pending.assert_called_once()
    call_kw = mock_referral.create_binding_from_pending.call_args[1]
    assert call_kw["creator_user_id"] == user_id
    assert "session" in call_kw


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
async def test_register_advertiser_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover transaction_manager path for register_advertiser, get_profile."""

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


@pytest.mark.asyncio
async def test_register_advertiser_user_not_found_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Raise UserNotFoundError when user missing and tm used."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(UserNotFoundError):
        await service.register_advertiser(
            user_id=UUID("00000000-0000-0000-0000-000000000121"),
            phone="@contact",
            brand="B",
        )


@pytest.mark.asyncio
async def test_update_advertiser_profile_success() -> None:
    """Update advertiser profile fields and return updated profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@old_contact",
        brand="Old Brand",
        site_link="https://old.com",
        city="Old City",
        company_activity="Old Activity",
    )

    updated = await service.update_advertiser_profile(
        user_id,
        phone="@new_contact",
        brand="New Brand",
        site_link="https://new.com",
        city="New City",
        company_activity="New Activity",
    )

    assert updated is not None
    assert updated.phone == "@new_contact"
    assert updated.brand == "New Brand"
    assert updated.site_link == "https://new.com"
    assert updated.city == "New City"
    assert updated.company_activity == "New Activity"


@pytest.mark.asyncio
async def test_update_advertiser_profile_partial_update() -> None:
    """Update only some fields, others remain unchanged."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="Brand",
        site_link="https://site.com",
        city="City",
        company_activity="Activity",
    )

    updated = await service.update_advertiser_profile(
        user_id, phone="@updated_phone"
    )

    assert updated is not None
    assert updated.phone == "@updated_phone"
    assert updated.brand == "Brand"
    assert updated.site_link == "https://site.com"


@pytest.mark.asyncio
async def test_update_advertiser_profile_preserves_optional_fields() -> None:
    """Regression: update_advertiser_profile must not drop optional fields."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    profile = AdvertiserProfile(
        user_id=user_id,
        phone="@p",
        brand="B",
        site_link="https://x.com",
        city="Moscow",
        company_activity="Activity",
        created_at=now,
        updated_at=now,
    )
    await advertiser_repo.save(profile)
    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    updated = await service.update_advertiser_profile(user_id, city="SPB")
    assert updated is not None
    assert updated.city == "SPB"
    assert updated.created_at == now
    saved = await advertiser_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.created_at == now
    assert saved.site_link == "https://x.com"


@pytest.mark.asyncio
async def test_update_advertiser_profile_returns_none_when_not_found() -> None:
    """Return None when profile does not exist."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    result = await service.update_advertiser_profile(
        UUID("00000000-0000-0000-0000-000000000999"),
        phone="@contact",
    )

    assert result is None


@pytest.mark.asyncio
async def test_update_advertiser_profile_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover transaction_manager path for update_advertiser_profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)

    service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=fake_tm,
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="Brand",
    )

    updated = await service.update_advertiser_profile(
        user_id, brand="Updated Brand"
    )

    assert updated is not None
    assert updated.brand == "Updated Brand"


@pytest.mark.asyncio
async def test_save_advertiser_before_agreement_empty_phone() -> None:
    """save_advertiser_before_agreement raises when phone is empty."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    with pytest.raises(AdvertiserRegistrationError):
        await service.save_advertiser_before_agreement(
            user_id=user_id,
            phone="  ",
            brand="B",
            site_link=None,
            city=None,
            company_activity=None,
            display_name=None,
        )


@pytest.mark.asyncio
async def test_save_advertiser_before_agreement_empty_brand() -> None:
    """save_advertiser_before_agreement raises when brand is empty."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    with pytest.raises(AdvertiserRegistrationError):
        await service.save_advertiser_before_agreement(
            user_id=user_id,
            phone="@contact",
            brand="  ",
            site_link=None,
            city=None,
            company_activity=None,
            display_name=None,
        )


@pytest.mark.asyncio
async def test_save_advertiser_before_agreement_user_not_found() -> None:
    """save_advertiser_before_agreement raises when user does not exist."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.save_advertiser_before_agreement(
            user_id=UUID("00000000-0000-0000-0000-000000000121"),
            phone="@contact",
            brand="B",
            site_link=None,
            city=None,
            company_activity=None,
            display_name=None,
        )


@pytest.mark.asyncio
async def test_confirm_advertiser_agreement_user_not_found() -> None:
    """confirm_advertiser_agreement raises when user does not exist."""

    service = AdvertiserRegistrationService(
        user_repo=InMemoryUserRepository(),
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.confirm_advertiser_agreement(
            user_id=UUID("00000000-0000-0000-0000-000000000121")
        )


async def _save_advertiser_before_agreement(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    user_id: UUID,
) -> None:
    """Helper: save advertiser profile before agreement (no confirm)."""

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    await service.save_advertiser_before_agreement(
        user_id=user_id,
        phone="@contact",
        brand="B",
        site_link=None,
        city=None,
        company_activity=None,
        display_name=None,
    )


@pytest.mark.asyncio
async def test_confirm_advertiser_agreement_calls_referral_and_metrics() -> (
    None
):
    """confirm_advertiser_agreement calls referral and metrics when set."""

    from unittest.mock import AsyncMock, Mock

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user(user_repo)
    await _save_advertiser_before_agreement(user_repo, advertiser_repo, user_id)
    mock_referral = Mock()
    mock_referral.create_binding_from_pending = AsyncMock(return_value=None)
    metrics = Mock()

    service = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        referral_service=mock_referral,
        metrics_collector=metrics,
    )

    await service.confirm_advertiser_agreement(user_id)

    mock_referral.create_binding_from_pending.assert_called_once()
    metrics.record_advertiser_registration.assert_called_once_with(str(user_id))


async def _seed_user_with_country(
    repo: InMemoryUserRepository, country: str
) -> UUID:
    """Seed a user with the given country code."""
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000121"),
        external_id="778",
        messenger_type=MessengerType.TELEGRAM,
        username="adv_cnt",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country=country,
    )
    await repo.save(user)
    return user.user_id


@pytest.mark.asyncio
async def test_register_advertiser_preserves_user_country() -> None:
    """register_advertiser must not overwrite user.country with None.

    Regression: the method previously constructed User(...) manually without
    the country field, which caused user.country to be reset to None in the DB.
    """

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user_with_country(user_repo, "kz")

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await service.register_advertiser(
        user_id=user_id,
        phone="@contact",
        brand="Brand KZ",
    )

    saved_user = await user_repo.get_by_id(user_id)
    assert saved_user is not None
    assert saved_user.country == "kz", (
        "user.country must be preserved after register_advertiser"
    )


@pytest.mark.asyncio
async def test_save_advertiser_before_agreement_preserves_user_country() -> (
    None
):
    """save_advertiser_before_agreement must not overwrite user.country.

    Regression: the method previously constructed User(...) manually without
    the country field, which caused user.country to be reset to None in the DB.
    """

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_id = await _seed_user_with_country(user_repo, "kz")

    service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )

    await service.save_advertiser_before_agreement(
        user_id=user_id,
        phone="@contact",
        brand="Brand KZ",
    )

    saved_user = await user_repo.get_by_id(user_id)
    assert saved_user is not None
    assert saved_user.country == "kz", (
        "user.country must be preserved after save_advertiser_before_agreement"
    )
