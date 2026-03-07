"""Rate limit store for Nominatim: in-memory (per process) or Redis (global)."""

import asyncio
import time
from typing import Protocol

# Redis key for "next allowed request" timestamp (wall clock).
NOMINATIM_RATE_LIMIT_KEY = "geocoder:nominatim:next_allowed"

# Lua: reserve next slot; return next_allowed (wall clock).
# KEYS[1] = key, ARGV[1] = now, ARGV[2] = delay_seconds
_RESERVE_SLOT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local delay = tonumber(ARGV[2])
local last = tonumber(redis.call('GET', key) or 0)
local next_allowed = math.max(now, last + delay)
redis.call('SET', key, next_allowed)
return tostring(next_allowed)
"""


class GeocoderRateLimitStore(Protocol):
    """Protocol for rate limit state (in-memory or Redis)."""

    async def wait_until_allowed(self) -> None:
        """Block until the next Nominatim request is allowed, then return."""
        ...


class InMemoryGeocoderRateLimitStore:
    """Per-process store: 1 req per delay_seconds inside this process."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = max(0.0, delay_seconds)
        self._lock = asyncio.Lock()
        self._last_request_time: float = 0.0

    async def wait_until_allowed(self) -> None:
        """Wait if needed, then record that a request is about to happen."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if (
                self._delay > 0
                and elapsed < self._delay
                and self._last_request_time > 0
            ):
                await asyncio.sleep(self._delay - elapsed)
            self._last_request_time = time.monotonic()


class RedisGeocoderRateLimitStore:
    """Redis-backed store: 1 req per delay_seconds across all app instances."""

    def __init__(self, redis_url: str, delay_seconds: float) -> None:
        self._redis_url = redis_url
        self._delay = max(0.0, delay_seconds)
        self._redis = None
        self._script_sha: str | None = None

    def _get_redis(self):
        """Lazy-init Redis client."""
        if self._redis is not None:
            return self._redis
        from redis.asyncio import Redis

        self._redis = Redis.from_url(
            self._redis_url,
            decode_responses=True,
        )
        return self._redis

    async def wait_until_allowed(self) -> None:
        """Reserve next slot in Redis, then sleep until that time."""
        if self._delay <= 0:
            return
        redis = self._get_redis()
        now = time.time()
        next_allowed_str = await redis.eval(
            _RESERVE_SLOT_SCRIPT,
            1,
            NOMINATIM_RATE_LIMIT_KEY,
            str(now),
            str(self._delay),
        )
        next_allowed = float(next_allowed_str)
        wait_sec = next_allowed - time.time()
        if wait_sec > 0:
            await asyncio.sleep(wait_sec)
