"""Redis-backed cache backend for geocoder results (CachePort)."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "geocoder:"


class GeocoderCacheRedis:
    """Async Redis cache for geocoder results (CachePort: str get/set)."""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._redis: "Redis | None" = None

    def _get_redis(self) -> "Redis | None":
        """Lazy-init Redis client with decode_responses=True for str values."""
        if self._redis is not None:
            return self._redis
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(
                self._redis_url,
                decode_responses=True,
            )
            return self._redis
        except ImportError:
            logger.debug(
                "Redis not installed, geocoder cache unavailable",
                extra={"redis_url": self._redis_url[:50]},
            )
            return None

    def _full_key(self, key: str) -> str:
        """Return key with prefix (caller may already use geocoder: in key)."""
        if self._key_prefix and not key.startswith(self._key_prefix):
            return f"{self._key_prefix}{key}"
        return key

    async def get(self, key: str) -> str | None:
        """Return cached JSON string or None."""
        redis = self._get_redis()
        if redis is None:
            return None
        try:
            full_key = self._full_key(key)
            return await redis.get(full_key)
        except Exception as exc:
            logger.warning(
                "Geocoder cache get failed",
                extra={"key": key, "error": str(exc)},
            )
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store value with TTL. No-op if Redis unavailable."""
        redis = self._get_redis()
        if redis is None:
            return
        try:
            full_key = self._full_key(key)
            await redis.setex(full_key, ttl_seconds, value)
        except Exception as exc:
            logger.warning(
                "Geocoder cache set failed",
                extra={"key": key, "error": str(exc)},
            )
