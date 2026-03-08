"""Tests for geocoder rate limit stores (in-memory and Redis)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.geocoder_rate_limit_store import (
    NOMINATIM_RATE_LIMIT_KEY,
    InMemoryGeocoderRateLimitStore,
    RedisGeocoderRateLimitStore,
)


@pytest.mark.asyncio
async def test_in_memory_store_zero_delay_returns_immediately() -> None:
    """In-memory store with delay 0 does not block."""
    store = InMemoryGeocoderRateLimitStore(delay_seconds=0)
    t0 = time.monotonic()
    await store.wait_until_allowed()
    await store.wait_until_allowed()
    assert time.monotonic() - t0 < 0.05


@pytest.mark.asyncio
async def test_in_memory_store_enforces_delay() -> None:
    """In-memory store waits at least delay_seconds between allows."""
    delay = 0.1
    store = InMemoryGeocoderRateLimitStore(delay_seconds=delay)
    await store.wait_until_allowed()
    t0 = time.monotonic()
    await store.wait_until_allowed()
    elapsed = time.monotonic() - t0
    assert elapsed >= delay


@pytest.mark.asyncio
async def test_redis_store_zero_delay_returns_immediately() -> None:
    """Redis store with delay 0 does not call Redis or block."""
    store = RedisGeocoderRateLimitStore(
        redis_url="redis://localhost:6379/0",
        delay_seconds=0,
    )
    await store.wait_until_allowed()
    # No Redis call when delay is 0
    assert store._redis is None


@pytest.mark.asyncio
async def test_redis_store_reserves_slot_via_lua() -> None:
    """Redis store calls eval with correct key and args."""
    store = RedisGeocoderRateLimitStore(
        redis_url="redis://localhost:6379/0",
        delay_seconds=1.0,
    )
    mock_redis = MagicMock()
    mock_redis.eval = AsyncMock(return_value="1234567890.5")
    store._redis = mock_redis

    await store.wait_until_allowed()

    mock_redis.eval.assert_called_once()
    call_args = mock_redis.eval.call_args[0]
    assert call_args[1] == 1  # numkeys
    assert call_args[2] == NOMINATIM_RATE_LIMIT_KEY
    assert call_args[4] == "1.0"  # delay_seconds


@pytest.mark.asyncio
async def test_redis_store_lazy_init_calls_from_url() -> None:
    """Redis store lazy-inits client via Redis.from_url when delay > 0."""
    with patch("redis.asyncio.Redis") as mock_redis_class:
        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=str(time.time() + 0.05))
        mock_redis_class.from_url = MagicMock(return_value=mock_redis)
        store = RedisGeocoderRateLimitStore(
            redis_url="redis://localhost:6379/1",
            delay_seconds=0.1,
        )
        assert store._redis is None
        await store.wait_until_allowed()
        mock_redis_class.from_url.assert_called_once_with(
            "redis://localhost:6379/1",
            decode_responses=True,
        )
        assert store._redis is mock_redis


@pytest.mark.asyncio
async def test_redis_store_waits_when_next_allowed_in_future() -> None:
    """Redis store sleeps when eval returns future timestamp."""
    store = RedisGeocoderRateLimitStore(
        redis_url="redis://localhost:6379/0",
        delay_seconds=0.2,
    )
    mock_redis = MagicMock()
    future_ts = time.time() + 0.05
    mock_redis.eval = AsyncMock(return_value=str(future_ts))
    store._redis = mock_redis
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await store.wait_until_allowed()
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] > 0
