"""Tests for blogger registration service."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    BloggerRegistrationError,
    UserNotFoundError,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
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

    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

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
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )

    assert profile.user_id == user_id
    assert profile.confirmed is False
    assert profile.birth_date == date(1995, 5, 15)
    assert profile.region is None
    assert profile.location_geometry is None


@pytest.mark.asyncio
async def test_register_blogger_with_geocoder_sets_location_geometry() -> None:
    """Geocoder returning coords sets profile.location_geometry and region."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    class FakeGeocoder:
        async def geocode(self, query, region=None):
            return (55.7558, 37.6173) if query else None

        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (
                55.7558,
                37.6173,
                "place",
                "city",
                "Москва",
                "Russia",
            )

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoder(),
    )

    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/geo_user",
        city="Moscow",
        topics={"selected": []},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.FEMALE,
        region="Москва",
    )

    assert profile.location_geometry == "MULTIPOINT((37.6173 55.7558))"
    assert profile.region == "Москва"
    assert profile.country == "Russia"


@pytest.mark.asyncio
async def test_register_blogger_geocoder_none_leaves_geometry_empty() -> None:
    """When geocoder returns None, profile has no location_geometry."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    class FakeGeocoder:
        async def geocode(self, query, region=None):
            return None

        async def geocode_with_details(self, query, region=None, country=None):
            return None

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return False

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return False

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoder(),
    )
    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/geo_user",
        city="UnknownCity",
        topics={"selected": []},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.FEMALE,
    )
    assert profile.location_geometry is None
    assert profile.city == "UnknownCity"


@pytest.mark.asyncio
async def test_resolve_city_from_location_returns_none_when_geocoder_none() -> (
    None
):
    """resolve_city_from_location returns None when geocoder is not set."""
    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        geocoder=None,
    )
    assert await service.resolve_city_from_location(55.75, 37.6) is None


@pytest.mark.asyncio
async def test_resolve_city_from_location_returns_result_from_geocoder() -> (
    None
):
    """resolve_city_from_location delegates to geocoder.reverse_geocode."""
    from unittest.mock import AsyncMock, MagicMock

    mock_geocoder = MagicMock()
    mock_geocoder.reverse_geocode = AsyncMock(
        return_value=("Kazan", "Tatarstan", "Russia")
    )
    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        geocoder=mock_geocoder,
    )
    result = await service.resolve_city_from_location(55.79, 49.12)
    assert result == ("Kazan", "Tatarstan", "Russia")
    mock_geocoder.reverse_geocode.assert_called_once_with(55.79, 49.12)


@pytest.mark.asyncio
async def test_resolve_city_to_location_returns_none_when_geocoder_none() -> (
    None
):
    """resolve_city_to_location returns None when geocoder is not set."""
    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        geocoder=None,
    )
    assert await service.resolve_city_to_location("Moscow") is None


@pytest.mark.asyncio
async def test_resolve_city_to_location_returns_wkt_and_region_country() -> (
    None
):
    """resolve_city_to_location returns (wkt, region, country) from geocoder."""
    from unittest.mock import AsyncMock, MagicMock

    mock_geocoder = MagicMock()
    mock_geocoder.geocode_with_details = AsyncMock(
        return_value=(
            55.7558,
            37.6173,
            "place",
            "city",
            "Moscow",
            "Russia",
        )
    )
    mock_geocoder.accepts_as_populated_place = MagicMock(return_value=True)
    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        geocoder=mock_geocoder,
    )
    result = await service.resolve_city_to_location("Moscow")
    assert result is not None
    wkt, region, country = result
    assert "MULTIPOINT" in wkt
    assert "37.6173" in wkt and "55.7558" in wkt
    assert region == "Moscow"
    assert country == "Russia"
    mock_geocoder.geocode_with_details.assert_called_once_with(
        "Moscow", region=None, country=None
    )


@pytest.mark.asyncio
async def test_register_blogger_duplicate_instagram_url() -> None:
    """Reject registration with duplicate Instagram URL."""
    from datetime import datetime, timezone

    from ugc_bot.domain.entities import BloggerProfile

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )

    assert "уже зарегистрирован" in str(exc_info.value)


@pytest.mark.asyncio
async def test_register_blogger_empty_instagram() -> None:
    """Reject empty Instagram URL."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_register_blogger_invalid_age() -> None:
    """Reject invalid audience age range."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_register_blogger_invalid_geo_and_price() -> None:
    """Reject missing geo and invalid price."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
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
            audience_geo="",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_register_blogger_non_positive_age_is_rejected() -> None:
    """Reject non-positive audience ages."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

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
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
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
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )

    metrics.record_blogger_registration.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_register_blogger_calls_referral_and_metrics_when_both_set() -> (
    None
):
    """register_blogger calls both referral and metrics when both are set."""

    from unittest.mock import AsyncMock, Mock

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    mock_referral = Mock()
    mock_referral.create_binding_from_pending = AsyncMock(return_value=None)
    metrics = Mock()

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        referral_service=mock_referral,
        metrics_collector=metrics,
    )

    await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/both_services",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )

    mock_referral.create_binding_from_pending.assert_called_once()
    metrics.record_blogger_registration.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_register_blogger_records_metrics_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Record metrics when collector and transaction_manager provided."""

    from unittest.mock import Mock

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    metrics = Mock()

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        metrics_collector=metrics,
        transaction_manager=fake_tm,
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
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )

    metrics.record_blogger_registration.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_register_blogger_with_transaction_manager(
    fake_tm: object,
) -> None:
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
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
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
    result = await service.get_profile_by_instagram_url(
        "https://instagram.com/with_tm"
    )
    assert result is not None
    assert result.instagram_url == "https://instagram.com/with_tm"


@pytest.mark.asyncio
async def test_increment_wanted_to_change_terms_count() -> None:
    """Increment wanted_to_change_terms_count for a blogger."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    profile = await blogger_repo.get_by_user_id(user_id)
    assert profile is None
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    await service.increment_wanted_to_change_terms_count(user_id)
    updated = await blogger_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.wanted_to_change_terms_count == 1
    await service.increment_wanted_to_change_terms_count(user_id)
    updated2 = await blogger_repo.get_by_user_id(user_id)
    assert updated2 is not None
    assert updated2.wanted_to_change_terms_count == 2


@pytest.mark.asyncio
async def test_update_blogger_profile_instagram_url_sets_confirmed_false() -> (
    None
):
    """When instagram_url is updated, confirmed must be set to False."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/old_user",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    result = await service.update_blogger_profile(
        user_id, instagram_url="https://instagram.com/new_user"
    )
    assert result.profile is not None
    updated = result.profile
    assert updated.instagram_url == "https://instagram.com/new_user"
    assert updated.confirmed is False


@pytest.mark.asyncio
async def test_update_blogger_profile_same_instagram_url_keeps_confirmed() -> (
    None
):
    """When instagram_url is unchanged, confirmed stays as is."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/same_user",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    result = await service.update_blogger_profile(
        user_id, instagram_url="https://instagram.com/same_user"
    )
    assert result.profile is not None
    updated = result.profile
    assert updated.instagram_url == "https://instagram.com/same_user"
    assert updated.confirmed is True


@pytest.mark.asyncio
async def test_update_blogger_profile_preserves_instagram_stats() -> None:
    """Updating profile must not clear instagram_user_id and instagram stats."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/stats_user",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
            instagram_user_id="ig_123",
            instagram_followers_count=5000,
            instagram_username="stats_user",
            instagram_stats_fetched_at=now,
        )
    )

    class FakeGeocoder:
        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (59.93, 30.31, "place", "city", "SPB", "Russia")

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoder(),
    )
    result = await service.update_blogger_profile(user_id, city="SPB")
    assert result.profile is not None
    updated = result.profile
    assert updated.city == "SPB"
    assert updated.instagram_user_id == "ig_123"
    assert updated.instagram_followers_count == 5000
    assert updated.instagram_username == "stats_user"
    assert updated.instagram_stats_fetched_at == now
    saved = await blogger_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_user_id == "ig_123"
    assert saved.instagram_followers_count == 5000


@pytest.mark.asyncio
async def test_increment_wanted_to_change_terms_preserves_instagram_stats() -> (
    None
):
    """increment_wanted_to_change_terms_count must not clear instagram stats."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/inc_user",
            confirmed=True,
            city="Moscow",
            topics={"selected": []},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
            instagram_user_id="ig_456",
            instagram_followers_count=10000,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    await service.increment_wanted_to_change_terms_count(user_id)
    saved = await blogger_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.wanted_to_change_terms_count == 1
    assert saved.instagram_user_id == "ig_456"
    assert saved.instagram_followers_count == 10000


# Optional fields of BloggerProfile that must be preserved by any update path.
# When adding a new optional field, add it here and set a value in
# _blogger_profile_with_all_optional_fields; if an update path drops it, fail.
_BLOGGER_PROFILE_OPTIONAL_FIELDS = (
    "wanted_to_change_terms_count",
    "created_at",
    "blogger_gender",
    "instagram_user_id",
    "instagram_followers_count",
    "instagram_username",
    "instagram_stats_fetched_at",
    "birth_date",
    "region",
    "location_geometry",
    "country",
)


def _blogger_profile_with_all_optional_fields(
    user_id: UUID, now: datetime
) -> BloggerProfile:
    """Profile with every optional field set for regression tests."""
    return BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/regression_user",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["lifestyle"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=20,
        audience_age_max=40,
        audience_geo="SPB",
        price=2000.0,
        barter=True,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=now,
        wanted_to_change_terms_count=5,
        created_at=now,
        blogger_gender=BloggerGender.FEMALE,
        instagram_user_id="ig_regression",
        instagram_followers_count=7000,
        instagram_username="regression_user",
        instagram_stats_fetched_at=now,
        birth_date=date(1990, 1, 1),
        region="Москва",
        location_geometry="MULTIPOINT((37.6 55.75))",
        country="russia",
    )


@pytest.mark.asyncio
async def test_update_blogger_profile_preserves_all_optional_fields() -> None:
    """Regression: update_blogger_profile must not drop any optional field."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    profile = _blogger_profile_with_all_optional_fields(user_id, now)
    await blogger_repo.save(profile)

    class FakeGeocoder:
        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (55.75, 37.6, "place", "city", "Москва", "russia")

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoder(),
    )
    result = await service.update_blogger_profile(user_id, city="Kazan")
    assert result.profile is not None, "expected profile update with geocoder"
    saved = await blogger_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.city == "Kazan"
    for field in _BLOGGER_PROFILE_OPTIONAL_FIELDS:
        assert getattr(saved, field) == getattr(profile, field), (
            f"update_blogger_profile must preserve {field}"
        )


@pytest.mark.asyncio
async def test_increment_preserves_all_optional_fields() -> None:
    """Regression: increment must not drop optional fields."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    profile = _blogger_profile_with_all_optional_fields(user_id, now)
    await blogger_repo.save(profile)
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    await service.increment_wanted_to_change_terms_count(user_id)
    saved = await blogger_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.wanted_to_change_terms_count == 6
    for field in _BLOGGER_PROFILE_OPTIONAL_FIELDS:
        if field == "wanted_to_change_terms_count":
            continue
        assert getattr(saved, field) == getattr(profile, field), (
            f"increment_wanted_to_change_terms_count must preserve {field}"
        )


@pytest.mark.asyncio
async def test_get_profile_by_instagram_url_without_transaction_manager() -> (
    None
):
    """Cover path without tm for get_profile_by_instagram_url."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/no_tm",
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
    )
    result = await service.get_profile_by_instagram_url(
        "https://instagram.com/no_tm"
    )
    assert result is not None
    assert result.instagram_url == "https://instagram.com/no_tm"


@pytest.mark.asyncio
async def test_register_blogger_user_not_found_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Raise UserNotFoundError when user missing and tm used."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        transaction_manager=fake_tm,
    )

    with pytest.raises(UserNotFoundError):
        await service.register_blogger(
            user_id=UUID("00000000-0000-0000-0000-000000000999"),
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_register_blogger_empty_city() -> None:
    """Reject empty city."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    with pytest.raises(BloggerRegistrationError):
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="   ",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_update_blogger_profile_returns_none_when_not_found() -> None:
    """Return None when profile does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    result = await service.update_blogger_profile(
        UUID("00000000-0000-0000-0000-000000000999"),
        city="Moscow",
    )

    assert result.profile is None
    assert result.location_geometry_resolved is True


@pytest.mark.asyncio
async def test_update_blogger_profile_with_geocoder_sets_geometry() -> None:
    """Updating city with geocoder sets location_geometry."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/geo_up",
            confirmed=False,
            city="OldCity",
            topics={"selected": []},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class FakeGeocoder:
        async def geocode(self, query, region=None):
            return (55.0, 37.0) if query else None

        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (55.0, 37.0, "place", "city", "Москва", "Russia")

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoder(),
    )
    result = await service.update_blogger_profile(
        user_id, city="Moscow", region="Москва"
    )
    assert result.profile is not None
    updated = result.profile
    assert updated.city == "Moscow"
    assert updated.region == "Москва"
    assert updated.country == "Russia"
    assert updated.location_geometry == "MULTIPOINT((37.0 55.0))"


@pytest.mark.asyncio
async def test_update_blogger_profile_city_not_place_returns_rejected() -> None:
    """When geocoder returns non-place (e.g. building), profile is not saved."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/geo_user",
            confirmed=False,
            city="OldCity",
            topics={"selected": []},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class FakeGeocoderNonPlace:
        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (55.0, 37.0, "building", "yes", None, None)

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return False

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return False

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        geocoder=FakeGeocoderNonPlace(),
    )
    result = await service.update_blogger_profile(user_id, city="SomeAddress")
    assert result.profile is None
    assert result.location_geometry_resolved is False
    saved = await blogger_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.city == "OldCity"


@pytest.mark.asyncio
async def test_update_blogger_profile_location_geometry_direct() -> None:
    """Updating location_geometry directly (e.g. from map) without geocoder."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/map_user",
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
            updated_at=now,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    wkt = "MULTIPOINT((37.62 55.75))"
    result = await service.update_blogger_profile(
        user_id, location_geometry=wkt
    )
    assert result.profile is not None
    updated = result.profile
    assert updated.city == "Moscow"
    assert updated.location_geometry == wkt


@pytest.mark.asyncio
async def test_update_blogger_profile_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover transaction_manager path for update_blogger_profile."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/tm_user",
            confirmed=False,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )

    class FakeGeocoder:
        async def geocode_with_details(self, query, region=None, country=None):
            if not query:
                return None
            return (59.93, 30.31, "place", "city", "SPB", "Russia")

        def accepts_as_populated_place(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

        def accepts_as_place_or_region(
            self, place_class: str, place_type: str
        ) -> bool:
            return True

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
        geocoder=FakeGeocoder(),
    )
    result = await service.update_blogger_profile(user_id, city="SPB")
    assert result.profile is not None
    updated = result.profile
    assert updated.city == "SPB"


@pytest.mark.asyncio
async def test_increment_wanted_to_change_terms_count_profile_not_found() -> (
    None
):
    """Do nothing when profile does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    await service.increment_wanted_to_change_terms_count(
        UUID("00000000-0000-0000-0000-000000000999")
    )


@pytest.mark.asyncio
async def test_increment_wanted_to_change_terms_count_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover transaction_manager path for increment_wanted_to_change_terms."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    now = datetime.now(timezone.utc)
    await blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=True,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=now,
        )
    )
    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
    )
    await service.increment_wanted_to_change_terms_count(user_id)
    updated = await blogger_repo.get_by_user_id(user_id)
    assert updated is not None
    assert updated.wanted_to_change_terms_count == 1


@pytest.mark.asyncio
async def test_register_blogger_validation_errors_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Cover validation error paths in transaction_manager branch."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
    )

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="   ",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "Instagram" in str(exc_info.value)

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="   ",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "City" in str(exc_info.value)

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="   ",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "geo" in str(exc_info.value).lower()

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=0,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "age" in str(exc_info.value).lower()

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=40,
            audience_age_max=30,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert (
        "max" in str(exc_info.value).lower()
        or "min" in str(exc_info.value).lower()
    )

    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=0.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "Price" in str(exc_info.value)


@pytest.mark.asyncio
async def test_register_blogger_duplicate_instagram_with_transaction_manager(
    fake_tm: object,
) -> None:
    """Reject duplicate Instagram URL when using transaction_manager."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
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
    await blogger_repo.save(
        BloggerProfile(
            user_id=user1.user_id,
            instagram_url="https://instagram.com/duplicate",
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
    )
    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=fake_tm,
    )
    with pytest.raises(BloggerRegistrationError) as exc_info:
        await service.register_blogger(
            user_id=user2.user_id,
            instagram_url="https://instagram.com/duplicate",
            city="SPB",
            topics={"selected": ["beauty"]},
            audience_gender=AudienceGender.FEMALE,
            audience_age_min=20,
            audience_age_max=30,
            audience_geo="SPB",
            price=2000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )
    assert "уже зарегистрирован" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_blogger_before_agreement_user_not_found() -> None:
    """save_blogger_before_agreement raises when user does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.save_blogger_before_agreement(
            user_id=UUID("00000000-0000-0000-0000-000000000999"),
            instagram_url="https://instagram.com/test",
            city="Moscow",
            topics={"selected": ["fitness"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1500.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            blogger_gender=BloggerGender.MALE,
            birth_date=date(1995, 5, 15),
        )


@pytest.mark.asyncio
async def test_save_blogger_before_agreement_with_location_geometry() -> None:
    """Stores location_geometry and country when provided."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
    )
    profile = await service.save_blogger_before_agreement(
        user_id=user_id,
        instagram_url="https://instagram.com/geo_blogger",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
        region="Moscow Oblast",
        location_geometry="POINT(37.6 55.75)",
        country="Russia",
    )
    assert profile.location_geometry == "POINT(37.6 55.75)"
    assert profile.region == "Moscow Oblast"
    assert profile.country == "Russia"


@pytest.mark.asyncio
async def test_confirm_blogger_agreement_user_not_found() -> None:
    """confirm_blogger_agreement raises when user does not exist."""

    service = BloggerRegistrationService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
    )

    with pytest.raises(UserNotFoundError):
        await service.confirm_blogger_agreement(
            user_id=UUID("00000000-0000-0000-0000-000000000999")
        )


@pytest.mark.asyncio
async def test_confirm_blogger_agreement_calls_referral_and_metrics() -> None:
    """confirm_blogger_agreement calls referral and metrics when set."""

    from unittest.mock import AsyncMock, Mock

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user(user_repo)
    service_save = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    await service_save.save_blogger_before_agreement(
        user_id=user_id,
        instagram_url="https://instagram.com/confirm_test",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )
    mock_referral = Mock()
    mock_referral.create_binding_from_pending = AsyncMock(return_value=None)
    metrics = Mock()

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        referral_service=mock_referral,
        metrics_collector=metrics,
    )

    await service.confirm_blogger_agreement(user_id)

    mock_referral.create_binding_from_pending.assert_called_once()
    metrics.record_blogger_registration.assert_called_once_with(str(user_id))


# ---------------------------------------------------------------------------
# Bug-fix regression tests: user.country not nullified, currency set from country  # noqa: E501
# ---------------------------------------------------------------------------


def _make_country_kz():
    """Return Kazakhstan Country entity."""
    from ugc_bot.domain.entities import Country

    return Country(
        code="kz",
        name_native="Қазақстан",
        currency_code="KZT",
        currency_symbol="₸",
        enabled=True,
    )


async def _seed_user_with_country(
    repo: InMemoryUserRepository, country: str
) -> UUID:
    """Seed a user with the given country code."""
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country=country,
    )
    await repo.save(user)
    return user.user_id


@pytest.mark.asyncio
async def test_confirm_blogger_agreement_preserves_user_country() -> None:
    """confirm_blogger_agreement must not overwrite user.country with None.

    Regression: the method previously constructed User(...) manually without
    the country field, which caused user.country to be reset to None in the DB.
    """

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user_with_country(user_repo, "kz")

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
    )

    # first save the profile (two-step flow)
    await service.save_blogger_before_agreement(
        user_id=user_id,
        instagram_url="https://instagram.com/alice",
        city="Almaty",
        topics={"selected": ["travel"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Kazakhstan",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.FEMALE,
        birth_date=date(1998, 3, 10),
    )

    await service.confirm_blogger_agreement(user_id)

    saved_user = await user_repo.get_by_id(user_id)
    assert saved_user is not None
    assert (
        saved_user.country == "kz"
    ), "user.country must be preserved after confirm_blogger_agreement"


@pytest.mark.asyncio
async def test_register_blogger_sets_currency_from_user_country() -> None:
    """register_blogger sets blogger_profiles.currency from user.country.

    Regression: the service previously left currency at the default 'RUB'
    regardless of the user's selected country.
    """
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    country_repo = InMemoryCountryRepository()
    country_repo.countries["kz"] = _make_country_kz()

    user_id = await _seed_user_with_country(user_repo, "kz")

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        country_repo=country_repo,
    )

    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/alice",
        city="Almaty",
        topics={"selected": ["travel"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Kazakhstan",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.FEMALE,
        birth_date=date(1998, 3, 10),
    )

    assert (
        profile.currency == "KZT"
    ), "blogger_profiles.currency must match the currency of user.country"


@pytest.mark.asyncio
async def test_register_blogger_currency_defaults_to_rub_without_country_repo() -> (  # noqa: E501
    None
):
    """register_blogger defaults currency to RUB when country_repo is absent."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    user_id = await _seed_user_with_country(user_repo, "kz")

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        # no country_repo
    )

    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/alice2",
        city="Almaty",
        topics={"selected": ["travel"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Kazakhstan",
        price=5000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.FEMALE,
        birth_date=date(1998, 3, 10),
    )

    assert profile.currency == "RUB"


@pytest.mark.asyncio
async def test_register_blogger_currency_defaults_to_rub_when_no_user_country() -> (  # noqa: E501
    None
):
    """register_blogger defaults currency to RUB when user has no country set."""  # noqa: E501
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    country_repo = InMemoryCountryRepository()
    country_repo.countries["kz"] = _make_country_kz()

    # user has no country
    user_id = await _seed_user(user_repo)

    service = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        country_repo=country_repo,
    )

    profile = await service.register_blogger(
        user_id=user_id,
        instagram_url="https://instagram.com/bob2",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Russia",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        blogger_gender=BloggerGender.MALE,
        birth_date=date(1995, 5, 15),
    )

    assert profile.currency == "RUB"
