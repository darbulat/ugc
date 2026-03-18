"""Redis-based rate limiter for multi-replica deployments."""

import logging
import time
from typing import Protocol

logger = logging.getLogger(__name__)

_RATE_LIMIT_PREFIX = "ugc:rate_limit:offer_response:"


class RateLimiterProtocol(Protocol):
    """Protocol for rate limiters (sync or async)."""

    async def allow(self, key: str) -> bool:
        """Return True when request is allowed."""
        ...


class RedisRateLimiter:
    """Sliding-window rate limiter using Redis, shared across replicas."""

    def __init__(
        self,
        redis_url: str,
        limit: int = 5,
        window_seconds: float = 10.0,
        socket_timeout: float = 5.0,
        socket_connect_timeout: float = 5.0,
        prefix: str = _RATE_LIMIT_PREFIX,
    ) -> None:
        self._redis_url = redis_url
        self._limit = limit
        self._window_seconds = window_seconds
        self._redis = None
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._prefix = prefix

    def _get_redis(self):
        """Lazy-init Redis client."""
        if self._redis is not None:
            return self._redis
        from redis.asyncio import Redis

        self._redis = Redis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_timeout=self._socket_timeout,
            socket_connect_timeout=self._socket_connect_timeout,
        )
        return self._redis

    async def allow(self, key: str) -> bool:
        """Return True when request is allowed (sliding window)."""
        redis = self._get_redis()
        redis_key = f"{self._prefix}{key}"
        now = time.time()
        window_start = now - self._window_seconds

        pipe = redis.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", window_start)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, int(self._window_seconds) + 1)
        results = await pipe.execute()

        count = results[2]
        if count > self._limit:
            await redis.zrem(redis_key, str(now))
            return False
        return True

    async def allow_async(self, key: str) -> bool:
        """Alias for allow (for unified interface with RateLimiter)."""
        return await self.allow(key)
