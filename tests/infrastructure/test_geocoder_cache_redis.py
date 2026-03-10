"""Tests for Redis geocoder cache backend."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.geocoder_cache_redis import (
    DEFAULT_PREFIX,
    GeocoderCacheRedis,
)


@pytest.mark.asyncio
async def test_redis_cache_lazy_init_and_get_set() -> None:
    """First get/set triggers lazy Redis init; get/set use client."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value="cached_value")
    mock_client.setex = AsyncMock()
    with patch("redis.asyncio.Redis") as m_redis:
        m_redis.from_url = MagicMock(return_value=mock_client)
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        val = await cache.get("geocode:hash1")
        assert val == "cached_value"
        await cache.set("geocode:hash2", "data", ttl_seconds=100)
        m_redis.from_url.assert_called_once()
        mock_client.get.assert_called_once()
        mock_client.setex.assert_called_once_with(
            f"{DEFAULT_PREFIX}geocode:hash2", 100, "data"
        )
        mock_client.reset_mock()
        mock_client.get = AsyncMock(return_value="v2")
        out = await cache.get("geocoder:reverse:xyz")
        assert out == "v2"
        call_key = mock_client.get.call_args[0][0]
        assert call_key == "geocoder:reverse:xyz"


@pytest.mark.asyncio
async def test_redis_cache_get_set_with_mock_client() -> None:
    """get/set use Redis client when available; key gets prefix."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value='{"cached": true}')
    mock_redis.setex = AsyncMock()
    with patch.object(
        GeocoderCacheRedis,
        "_get_redis",
        return_value=mock_redis,
    ):
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        value = await cache.get("geocode:abc123")
        assert value == '{"cached": true}'
        mock_redis.get.assert_called_once()
        call_key = mock_redis.get.call_args[0][0]
        assert call_key == f"{DEFAULT_PREFIX}geocode:abc123"

        await cache.set("geocode:xyz", "data", ttl_seconds=3600)
        mock_redis.setex.assert_called_once_with(
            f"{DEFAULT_PREFIX}geocode:xyz", 3600, "data"
        )


@pytest.mark.asyncio
async def test_redis_cache_get_returns_none_when_client_unavailable() -> None:
    """get returns None when _get_redis returns None (Redis unavailable)."""
    with patch.object(
        GeocoderCacheRedis,
        "_get_redis",
        return_value=None,
    ):
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        assert await cache.get("any") is None


@pytest.mark.asyncio
async def test_redis_cache_set_noop_when_client_unavailable() -> None:
    """set is a no-op when _get_redis returns None."""
    with patch.object(
        GeocoderCacheRedis,
        "_get_redis",
        return_value=None,
    ):
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        await cache.set("k", "v", ttl_seconds=60)
        # no exception, no call to Redis


@pytest.mark.asyncio
async def test_redis_cache_get_returns_none_on_redis_error() -> None:
    """get returns None and logs when Redis get raises."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch.object(
        GeocoderCacheRedis,
        "_get_redis",
        return_value=mock_redis,
    ):
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        assert await cache.get("key") is None


@pytest.mark.asyncio
async def test_redis_cache_set_handles_redis_error() -> None:
    """set does not raise when Redis setex raises; error is logged."""
    mock_redis = MagicMock()
    mock_redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch.object(
        GeocoderCacheRedis,
        "_get_redis",
        return_value=mock_redis,
    ):
        cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
        await cache.set("k", "v", ttl_seconds=60)


def test_get_redis_returns_none_on_import_error() -> None:
    """_get_redis returns None and logs when the redis package is not installed.

    This covers the ImportError branch inside _get_redis (lines 38-43 of
    geocoder_cache_redis.py) where ``from redis.asyncio import Redis`` raises.
    """
    cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
    # Simulate redis package being absent by making the import raise
    with patch(
        "ugc_bot.infrastructure.geocoder_cache_redis.GeocoderCacheRedis._get_redis",  # noqa: E501
        wraps=None,
    ):
        pass  # just confirming the method exists; test via builtins below

    # Patch builtins.__import__ to raise ImportError for redis.asyncio
    import builtins

    real_import = builtins.__import__

    def _import_that_fails_for_redis(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "redis.asyncio":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import_that_fails_for_redis):
        result = cache._get_redis()

    assert result is None


@pytest.mark.asyncio
async def test_redis_cache_set_is_noop_when_get_redis_returns_none_directly() -> (  # noqa: E501
    None
):
    """set() is a no-op when _get_redis() returns None (ImportError path).

    Exercises lines 38-43 of geocoder_cache_redis.py: the set() early-return
    branch when redis is unavailable, reached via the ImportError fallback.
    """
    cache = GeocoderCacheRedis(redis_url="redis://localhost:6379/0")
    # Force _get_redis to return None via ImportError simulation
    import builtins

    real_import = builtins.__import__

    def _import_that_fails_for_redis(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "redis.asyncio":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_import_that_fails_for_redis):
        # Should not raise; set() must return early when redis is None
        await cache.set("k", "v", ttl_seconds=60)
        # get() also returns None
        result = await cache.get("k")

    assert result is None
