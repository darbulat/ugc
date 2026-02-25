"""Tests for Instagram stats collector service."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.errors import ScrapeCreatorsAPIError
from ugc_bot.application.ports import InstagramStatsProviderClient
from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
    _extract_instagram_id,
    _extract_typed_fields,
    _username_from_profile,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.domain.enums import AudienceGender, WorkFormat
from ugc_bot.infrastructure.instagram.stats_provider_wrappers import (
    SingleProviderWrapper,
)
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


def test_extract_typed_fields_username_from_url_without_slash() -> None:
    """Username from data.url when url has no slash (single segment)."""
    raw = {
        "data": {
            "counts": {"followed_by": 10},
            "url": "single_handle",
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert u == "single_handle"


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


def test_extract_typed_fields_data_not_dict_uses_raw_top_level() -> None:
    """When data is not a dict, extract from raw top-level keys."""
    raw = {"data": [], "username": "top", "biography": "bio text"}
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f is None
    assert fo is None
    assert m is None
    assert u == "top"
    assert b == "bio text"


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


def test_username_from_profile_url_without_slash_returns_username() -> None:
    """When URL has no slash, whole value (minus query) is username."""
    profile = BloggerProfile(
        user_id=uuid4(),
        instagram_url="single_nick",
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
    assert _username_from_profile(profile) == "single_nick"


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
    from ugc_bot.application.services.instagram_stats_collector_service import (
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


def test_extract_typed_fields_web_profile_info() -> None:
    """Extract from Instagram web_profile_info data.user (edge_*)."""
    raw = {
        "data": {
            "user": {
                "username": "darbulat",
                "biography": "My bio",
                "edge_followed_by": {"count": 1000},
                "edge_follow": {"count": 200},
                "edge_owner_to_timeline_media": {"count": 50},
            },
        },
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 1000
    assert fo == 200
    assert m == 50
    assert u == "darbulat"
    assert b == "My bio"


def test_extract_typed_fields_web_profile_info_real_shape() -> None:
    """Parse real web_profile_info (edge_* with count, page_info, edges)."""
    raw = {
        "data": {
            "user": {
                "username": "_adelya_osipova_",
                "biography": (
                    "Менеджер внешней рекламы\nВнедряю спорт в свою жизнь"
                ),
                "edge_followed_by": {"count": 1626},
                "edge_follow": {"count": 556},
                "edge_owner_to_timeline_media": {
                    "count": 93,
                    "page_info": {
                        "has_next_page": True,
                        "end_cursor": "QVFDQnBM...",
                    },
                    "edges": [],
                },
            },
        },
        "status": "ok",
    }
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f == 1626
    assert fo == 556
    assert m == 93
    assert u == "_adelya_osipova_"
    assert "Менеджер внешней рекламы" in (b or "")


def test_extract_typed_fields_data_not_dict_uses_raw_fallback() -> None:
    """When data is not a dict, use raw for username/biography fallback."""
    raw = {"data": "invalid", "username": "x", "biography": "b"}
    f, fo, m, u, b = _extract_typed_fields(raw)
    assert f is None
    assert fo is None
    assert m is None
    assert u == "x"
    assert b == "b"


def test_extract_instagram_id_from_data_user() -> None:
    """Extract id from data.user.id (ScrapeCreators shape)."""
    assert _extract_instagram_id({"data": {"user": {"id": "123"}}}) == "123"


def test_extract_instagram_id_from_data_id() -> None:
    """Extract id from data.id when no data.user."""
    assert _extract_instagram_id({"data": {"id": "456"}}) == "456"


def test_extract_instagram_id_from_top_level() -> None:
    """Extract id from top-level id."""
    assert _extract_instagram_id({"id": "789"}) == "789"


def test_extract_instagram_id_returns_none_when_no_id() -> None:
    """Return None when no id in raw."""
    assert _extract_instagram_id({}) is None
    assert _extract_instagram_id({"data": {}}) is None
    assert _extract_instagram_id({"data": {"user": {}}}) is None


@pytest.mark.asyncio
async def test_run_once_no_client_returns_zero() -> None:
    """run_once returns (0, 0) when stats provider client is None."""
    blogger_repo = InMemoryBloggerProfileRepository()
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=None,
    )
    result = await service.run_once()
    assert result.updated == 0
    assert result.errors == 0


@pytest.mark.asyncio
async def test_run_once_empty_list_returns_zero() -> None:
    """run_once returns (0, 0) when no confirmed profiles."""
    blogger_repo = InMemoryBloggerProfileRepository()
    stats_repo = InMemoryInstagramStatsRepository()
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(), "rapid_api"
    )
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
    )
    result = await service.run_once()
    assert result.updated == 0
    assert result.errors == 0


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
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(profile_by_username={"jane": raw}),
        "rapid_api",
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    result = await service.run_once()
    assert result.updated == 1
    assert result.errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.user_id == user_id
    assert saved.raw_response == raw
    assert saved.followers_count == 2000
    assert saved.follows_count == 300
    assert saved.media_count == 100
    assert saved.instagram_username == "jane"
    assert saved.biography == "Bio"
    assert saved.provider == "rapid_api"
    assert saved.fetched_at is not None


class _NoDataProviderClient(InstagramStatsProviderClient):
    """Provider that always returns no data (for aiograpi fallback test)."""

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> tuple[dict | None, str]:
        return (None, "scrapecreators")


class _MockAiograpiFetcher:
    """Mock aiograpi fetcher that returns given raw dict."""

    def __init__(self, raw: dict):
        self._raw = raw

    async def get_profile_stats_by_username(self, username: str) -> dict | None:
        return self._raw


@pytest.mark.asyncio
async def test_run_once_uses_aiograpi_fallback_when_provider_empty() -> None:
    """When primary returns no data, aiograpi is used and stats saved."""
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

    aiograpi_raw = {
        "data": {
            "username": "jane",
            "followers_count": 1500,
            "follows_count": 200,
            "media_count": 80,
            "biography": "Aiograpi bio",
        },
        "id": "12345678",
    }
    client = _NoDataProviderClient()
    aiograpi_fetcher = _MockAiograpiFetcher(aiograpi_raw)
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        aiograpi_fetcher=aiograpi_fetcher,
        batch_size=10,
        delay_seconds=0.0,
    )

    result = await service.run_once()
    assert result.updated == 1
    assert result.errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.followers_count == 1500
    assert saved.follows_count == 200
    assert saved.media_count == 80
    assert saved.instagram_username == "jane"
    assert saved.biography == "Aiograpi bio"
    assert saved.provider == "aiograpi"
    assert saved.instagram_id == "12345678"


@pytest.mark.asyncio
async def test_run_once_saves_instagram_id_when_data_user_has_id() -> None:
    """When raw has data.user.id (e.g. ScrapeCreators), instagram_id saved."""
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
        "success": True,
        "data": {
            "user": {
                "id": "2700692569",
                "username": "jane",
                "biography": "Bio",
                "edge_followed_by": {"count": 100},
                "edge_follow": {"count": 50},
                "edge_owner_to_timeline_media": {"count": 10},
            }
        },
        "status": "ok",
    }
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(profile_by_username={"jane": raw}),
        "scrapecreators",
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    result = await service.run_once()
    assert result.updated == 1
    assert result.errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_id == "2700692569"
    assert saved.followers_count == 100
    assert saved.follows_count == 50
    assert saved.media_count == 10
    assert saved.instagram_username == "jane"
    assert saved.biography == "Bio"


@pytest.mark.asyncio
async def test_run_once_saves_instagram_id_from_data_id() -> None:
    """When raw has data.id but no data.user, instagram_id is still saved."""
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
        "success": True,
        "data": {
            "id": "456",
            "username": "jane",
            "followers_count": 10,
            "follows_count": 5,
            "media_count": 2,
            "biography": "Bio",
        },
        "status": "ok",
    }
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(profile_by_username={"jane": raw}),
        "scrapecreators",
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    result = await service.run_once()
    assert result.updated == 1
    assert result.errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_id == "456"


@pytest.mark.asyncio
async def test_run_once_saves_instagram_id_from_top_level_id() -> None:
    """When raw has top-level id only, instagram_id is still saved."""
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
        "id": "789",
        "username": "jane",
        "followers_count": 1,
        "follows_count": 0,
        "media_count": 0,
        "biography": "",
    }
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(profile_by_username={"jane": raw}),
        "rapid_api",
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        batch_size=10,
        delay_seconds=0.0,
    )

    result = await service.run_once()
    assert result.updated == 1
    assert result.errors == 0

    saved = await stats_repo.get_by_user_id(user_id)
    assert saved is not None
    assert saved.instagram_id == "789"


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
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(), "rapid_api"
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        delay_seconds=0.0,
    )
    result = await service.run_once()
    assert result.updated == 0
    assert result.errors == 1
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
    client = SingleProviderWrapper(
        InMemoryInstagramRapidApiClient(profile_by_username={}), "rapid_api"
    )
    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=client,
        delay_seconds=0.0,
    )
    result = await service.run_once()
    assert result.updated == 0
    assert result.errors == 1


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
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=SingleProviderWrapper(
            FailingClient(), "rapid_api"
        ),
        delay_seconds=0.0,
    )
    result = await service.run_once()
    assert result.updated == 0
    assert result.errors == 1


@pytest.mark.asyncio
async def test_run_once_scrapecreators_api_error_propagates() -> None:
    """ScrapeCreatorsAPIError from client is re-raised for alerting."""
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

    class ScrapeCreatorsFailingClient(InMemoryInstagramRapidApiClient):
        async def get_profile_stats_by_username(self, username: str):
            raise ScrapeCreatorsAPIError(
                "ScrapeCreators API error: 402",
                status_code=402,
                response_text='{"message":"out of credits"}',
            )

    stats_repo = InMemoryInstagramStatsRepository()
    service = InstagramStatsCollectorService(
        blogger_repo=blogger_repo,
        instagram_stats_repo=stats_repo,
        stats_provider_client=SingleProviderWrapper(
            ScrapeCreatorsFailingClient(), "scrapecreators"
        ),
        delay_seconds=0.0,
    )
    with pytest.raises(ScrapeCreatorsAPIError) as exc_info:
        await service.run_once()
    assert exc_info.value.status_code == 402
