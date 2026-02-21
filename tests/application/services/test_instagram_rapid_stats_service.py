"""Tests for Instagram Rapid API stats collector service."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.services.instagram_rapid_stats_service import (
    InstagramRapidStatsCollectorService,
    _extract_typed_fields,
    _username_from_profile,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender, WorkFormat
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramRapidApiClient,
    InMemoryInstagramStatsRepository,
)


def test_extract_typed_fields_from_data_counts() -> None:
    """Extract from data.counts shape (e.g. instagram-v2)."""
    raw = {
        "data": {
            "username": "jane",
            "counts": {
                "followed_by": 2000,
                "follows": 300,
                "media": 100,
            },
            "biography": "Bio text",
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 2000
    assert fo == 300
    assert m == 100
    assert u == "jane"
    assert b == "Bio text"


def test_extract_typed_fields_from_data_top_level() -> None:
    """Extract from data.* top-level fields."""
    raw = {
        "data": {
            "username": "bob",
            "followers_count": 5000,
            "follows_count": 400,
            "media_count": 200,
            "bio": "Hello",
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 5000
    assert fo == 400
    assert m == 200
    assert u == "bob"
    assert b == "Hello"


def test_extract_typed_fields_empty_raw() -> None:
    """Empty or invalid raw returns Nones."""
    assert _extract_typed_fields({}) == (None, None, None, None, None)


def test_username_from_profile_uses_instagram_username() -> None:
    """Prefer instagram_username when set."""
    profile = BloggerProfile(
        user_id=uuid4(),
        instagram_url="https://instagram.com/url_nick",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_username="profile_nick",
    )
    assert _username_from_profile(profile) == "profile_nick"


def test_username_from_profile_parses_url() -> None:
    """Fallback to last path segment of instagram_url."""
    profile = BloggerProfile(
        user_id=uuid4(),
        instagram_url="https://instagram.com/parsed_nick",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_username=None,
    )
    assert _username_from_profile(profile) == "parsed_nick"


def test_username_from_profile_empty_url_returns_none() -> None:
    """Return None when instagram_url is empty."""
    profile = BloggerProfile(
        user_id=uuid4(),
        instagram_url="",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_username=None,
    )
    assert _username_from_profile(profile) is None


def test_extract_typed_fields_raw_top_level_username_bio() -> None:
    """Extract username/biography from top-level when data is not a dict."""
    raw = {"username": "top", "biography": "top bio"}
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert u == "top"
    assert b == "top bio"
    assert f is None
    assert fo is None
    assert m is None


def test_extract_typed_fields_data_without_counts() -> None:
    """Data dict without counts uses _extract_from_data."""
    raw = {
        "data": {
            "username": "alice",
            "followers_count": 1000,
            "follows_count": 100,
            "media_count": 50,
            "bio": "Hello",
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 1000
    assert fo == 100
    assert m == 50
    assert u == "alice"
    assert b == "Hello"


def test_extract_typed_fields_instagram_statistics_api_shape() -> None:
    """Extract from instagram-statistics-api /community response shape."""
    raw = {
        "data": {
            "usersCount": 48119,
            "screenName": "history_kzn",
            "url": "https://instagram.com/history_kzn",
            "description": "▪️Ценитель архитектуры, истории и города Казани",
            "name": "Руслан Бикуев «История Казани»",
        },
        "meta": {"code": 200, "message": "OK"},
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 48119
    assert u == "history_kzn"
    assert b == "▪️Ценитель архитектуры, истории и города Казани"
    assert fo is None
    assert m is None


def test_extract_typed_fields_username_from_url_when_no_screenname() -> None:
    """Username parsed from data.url when username/screenName missing."""
    from ugc_bot.application.services.instagram_rapid_stats_service import (
        _username_from_url,
    )

    assert (
        _username_from_url("https://instagram.com/history_kzn") == "history_kzn"
    )
    assert (
        _username_from_url("https://instagram.com/history_kzn/")
        == "history_kzn"
    )
    assert _username_from_url("") is None
    assert _username_from_url(None) is None

    raw = {
        "data": {
            "counts": {"followed_by": 100},
            "url": "https://instagram.com/some_user/",
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert u == "some_user"
    assert f == 100


def test_extract_typed_fields_non_numeric_counts_returns_none() -> None:
    """Non-numeric count values are coerced to None."""
    raw = {
        "data": {
            "username": "x",
            "counts": {
                "followed_by": "not_a_number",
                "follows": 1,
                "media": 2,
            },
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f is None
    assert fo == 1
    assert m == 2
    assert u == "x"


@pytest.mark.asyncio
async def test_run_once_no_client_returns_zero() -> None:
    """run_once returns (0, 0) when Rapid API client is None."""
    blogger_repo = InMemoryBloggerProfileRepository()
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=None,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_empty_list_returns_zero() -> None:
    """run_once returns (0, 0) when no confirmed profiles."""
    blogger_repo = InMemoryBloggerProfileRepository()
    stats_repo = InMemoryInstagramStatsRepository()
    client = InMemoryInstagramRapidApiClient()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=client,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 0


@pytest.mark.asyncio
async def test_run_once_saves_stats_from_rapid_api() -> None:
    """run_once fetches via client and saves InstagramStats."""
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
        instagram_username="jane",
    )
    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    raw = {
        "data": {
            "username": "jane",
            "counts": {
                "followed_by": 2000,
                "follows": 300,
                "media": 100,
            },
            "biography": "Bio",
        },
    }
    client = InMemoryInstagramRapidApiClient(
        profile_by_username={"jane": raw},
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    updated, errors = await service.run_once()
    assert updated == 1
    assert errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.user_id == user_id
    assert saved.raw_response == raw
    assert saved.followers_count == 2000
    assert saved.follows_count == 300
    assert saved.media_count == 100
    assert saved.instagram_username == "jane"
    assert saved.biography == "Bio"
    assert saved.fetched_at is not None


@pytest.mark.asyncio
async def test_run_once_skips_profile_without_username() -> None:
    """Profile with no instagram_username and empty URL counts as error."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_1",
        instagram_username=None,
    )
    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    client = InMemoryInstagramRapidApiClient()
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=client,
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1
    assert await stats_repo.get_by_user_id(user_id) is None


@pytest.mark.asyncio
async def test_run_once_client_returns_none_increments_errors() -> None:
    """When client returns None, count as error."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/missing",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_1",
        instagram_username="missing",
    )
    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)
    client = InMemoryInstagramRapidApiClient(profile_by_username={})
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=client,
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1


@pytest.mark.asyncio
async def test_run_once_client_raises_increments_errors() -> None:
    """When client raises, count as error."""
    user_id = uuid4()
    profile = BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/jane",
        confirmed=True,
        city="",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="",
        price=0.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
        instagram_user_id="ig_1",
        instagram_username="jane",
    )
    blogger_repo = InMemoryBloggerProfileRepository()
    await blogger_repo.save(profile)

    class FailingClient(InMemoryInstagramRapidApiClient):
        async def get_profile_stats_by_username(self, username: str):
            raise ValueError("network error")

    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramRapidStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        rapid_api_client=FailingClient(),
        delay_seconds=0.0,
    )
    updated, errors = await service.run_once()
    assert updated == 0
    assert errors == 1
