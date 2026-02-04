"""Redis-based lock for serializing per-user operations across processes."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "ugc:lock:issue_desc:"
_LOCK_TIMEOUT = 30


class IssueDescriptionLockManager:
    """Per-user lock for issue description state updates.

    Uses Redis when available (works across processes/instances),
    falls back to in-memory lock otherwise.
    """

    def __init__(self, redis_url: str | None) -> None:
        self._redis_url = redis_url
        self._redis: "Redis | None" = None
        self._memory_locks: dict[str, asyncio.Lock] = {}

    def _get_redis(self) -> "Redis | None":
        """Lazy-init Redis client."""
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(self._redis_url, decode_responses=True)
            return self._redis
        except ImportError:
            logger.debug("Redis not installed, using in-memory lock")
            return None

    @asynccontextmanager
    async def lock(self, user_id: str) -> AsyncIterator[None]:
        """Acquire per-user lock. Use Redis when available."""
        redis = self._get_redis()
        if redis is not None:
            lock_key = f"{_LOCK_PREFIX}{user_id}"
            try:
                async with redis.lock(lock_key, timeout=_LOCK_TIMEOUT):
                    yield
            except Exception as exc:
                logger.warning(
                    "Redis lock failed, falling back to in-memory",
                    extra={"user_id": user_id, "error": str(exc)},
                )
                async with self._memory_lock(user_id):
                    yield
        else:
            async with self._memory_lock(user_id):
                yield

    @asynccontextmanager
    async def _memory_lock(self, user_id: str) -> AsyncIterator[None]:
        """In-process lock fallback."""
        if user_id not in self._memory_locks:
            self._memory_locks[user_id] = asyncio.Lock()
        async with self._memory_locks[user_id]:
            yield
