"""Tests for Instagram stats update service."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.application.services.instagram_stats_update_service import (
    InstagramStatsUpdateService,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender, WorkFormat
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramGraphApiClient,
)


@pytest.mark.asyncio
async def test_run_once_no_client_returns_zero() -> None:
    """run_once returns (0, 0) when API client is None."""
    repo = InMemoryBloggerProfileRepository()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=None,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_empty_list_returns_zero() -> None:
    """run_once returns (0, 0) when no profiles have instagram_user_id."""
    repo = InMemoryBloggerProfileRepository()
    client = InMemoryInstagramGraphApiClient()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_updates_profile_stats() -> None:
    """run_once fetches API and updates profile with new stats."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="jane",
        followers_count=2000,
        media_count=100,
        follows_count=300,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_123": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_followers_count == 2000
    assert saved.instagram_media_count == 100
    assert saved.instagram_follows_count == 300
    assert saved.instagram_username == "jane"
    assert saved.instagram_stats_fetched_at is not None
    assert saved.instagram_url == "https://instagram.com/jane"


@pytest.mark.asyncio
async def test_run_once_updates_instagram_url_from_username() -> None:
    """When API returns username, instagram_url is set to canonical URL."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/old_nickname",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_456",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="canonical_handle",
        followers_count=5000,
        media_count=200,
        follows_count=100,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_456": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_url == "https://instagram.com/canonical_handle"
    assert saved.instagram_username == "canonical_handle"


@pytest.mark.asyncio
async def test_run_once_increments_errors_when_api_returns_none() -> None:
    """run_once counts errors when get_profile_by_id returns None."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_unknown",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)
    client = InMemoryInstagramGraphApiClient()
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1


@pytest.mark.asyncio
async def test_run_once_preserves_location_geometry() -> None:
    """run_once does not overwrite location_geometry when updating stats."""
    user_id = uuid4()
    geometry_wkt = "MULTIPOINT((37.6 55.75))"
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
        location_geometry=geometry_wkt,
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    api_profile = InstagramProfileInfo(
        username="jane",
        followers_count=2000,
        media_count=100,
        follows_count=300,
    )
    client = InMemoryInstagramGraphApiClient(
        profile_map={"ig_123": api_profile},
    )
    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.location_geometry == geometry_wkt
    assert saved.instagram_followers_count == 2000


@pytest.mark.asyncio
async def test_run_once_handles_api_exception() -> None:
    """run_once logs and counts error when get_profile_by_id raises."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=100.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_123",
    )
    repo = InMemoryBloggerProfileRepository()
    await repo.save(profile)

    class RaisingClient(InMemoryInstagramGraphApiClient):
        async def get_profile_by_id(self, instagram_user_id: str):
            raise ValueError("API error")

    service = InstagramStatsUpdateService(
        blogger_repo=repo,
        instagram_api_client=RaisingClient(),
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1
