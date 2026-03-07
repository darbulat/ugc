"""Tests for in-memory geocoder cache backend."""

import time

import pytest

from ugc_bot.infrastructure.geocoder_cache_memory import GeocoderCacheMemory


@pytest.mark.asyncio
async def test_memory_cache_set_then_get() -> None:
    """After set, get returns the value within TTL."""
    cache = GeocoderCacheMemory(max_entries=100)
    await cache.set("k1", "v1", ttl_seconds=60)
    assert await cache.get("k1") == "v1"


@pytest.mark.asyncio
async def test_memory_cache_get_missing_returns_none() -> None:
    """get for unknown key returns None."""
    cache = GeocoderCacheMemory(max_entries=100)
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_memory_cache_expired_returns_none() -> None:
    """Entry with ttl_seconds=0 is considered expired on next get."""
    cache = GeocoderCacheMemory(max_entries=100)
    await cache.set("k", "v", ttl_seconds=0)
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_memory_cache_get_evicts_expired_entry() -> None:
    """get removes expired entry from store and returns None."""
    cache = GeocoderCacheMemory(max_entries=100)
    await cache.set("expire_soon", "x", ttl_seconds=1)
    time.sleep(1.1)
    assert await cache.get("expire_soon") is None
    assert await cache.get("expire_soon") is None


@pytest.mark.asyncio
async def test_memory_cache_evicts_when_over_max_entries() -> None:
    """When max_entries is 2, third set evicts oldest."""
    cache = GeocoderCacheMemory(max_entries=2)
    await cache.set("a", "1", ttl_seconds=60)
    await cache.set("b", "2", ttl_seconds=60)
    assert await cache.get("a") == "1"
    assert await cache.get("b") == "2"
    await cache.set("c", "3", ttl_seconds=60)
    assert await cache.get("c") == "3"
    assert await cache.get("a") is None
    assert await cache.get("b") == "2"
