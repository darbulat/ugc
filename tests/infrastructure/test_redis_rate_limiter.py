"""Tests for Redis-based rate limiter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.redis_rate_limiter import (
    RateLimiterProtocol,
    RedisRateLimiter,
)


@pytest.mark.asyncio
async def test_allow_under_limit_returns_true() -> None:
    """allow returns True when request count is under limit."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[None, None, 3, True])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mock_redis.zrem = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.Redis.from_url",
        return_value=mock_redis,
    ):
        limiter = RedisRateLimiter(
            redis_url="redis://localhost",
            limit=5,
            window_seconds=10.0,
        )
        result = await limiter.allow("user123")

    assert result is True
    mock_pipe.zremrangebyscore.assert_called_once()
    mock_pipe.zadd.assert_called_once()
    mock_pipe.zcard.assert_called_once()
    mock_pipe.expire.assert_called_once()
    mock_redis.zrem.assert_not_called()


@pytest.mark.asyncio
async def test_allow_over_limit_returns_false() -> None:
    """allow returns False and removes current timestamp when over limit."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[None, None, 6, True])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mock_redis.zrem = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.Redis.from_url",
        return_value=mock_redis,
    ):
        limiter = RedisRateLimiter(
            redis_url="redis://localhost",
            limit=5,
            window_seconds=10.0,
        )
        result = await limiter.allow("user456")

    assert result is False
    mock_redis.zrem.assert_called_once()


@pytest.mark.asyncio
async def test_allow_async_alias() -> None:
    """allow_async delegates to allow."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[None, None, 1, True])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mock_redis.zrem = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.Redis.from_url",
        return_value=mock_redis,
    ):
        limiter = RedisRateLimiter(redis_url="redis://localhost")
        result = await limiter.allow_async("key")

    assert result is True


@pytest.mark.asyncio
async def test_get_redis_lazy_init() -> None:
    """_get_redis creates client on first use and reuses it."""
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=MagicMock())
    mock_redis.pipeline.return_value.execute = AsyncMock(
        return_value=[None, None, 0, True]
    )
    mock_redis.zrem = AsyncMock(return_value=None)

    with patch(
        "redis.asyncio.Redis.from_url",
        return_value=mock_redis,
    ) as from_url:
        limiter = RedisRateLimiter(redis_url="redis://localhost:6379")
        assert limiter._redis is None

        await limiter.allow("k1")
        from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )
        assert limiter._redis is mock_redis

        await limiter.allow("k2")
        from_url.assert_called_once()


def test_rate_limiter_protocol_structural() -> None:
    """RedisRateLimiter satisfies RateLimiterProtocol (structural subtyping)."""
    limiter: RateLimiterProtocol = RedisRateLimiter(redis_url="redis://x")
    assert hasattr(limiter, "allow")
    assert callable(limiter.allow)
