"""Redis-backed cache for admin dashboard and list responses."""

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_ADMIN_CACHE_PREFIX = "admin:cache:"


def _json_encoder_default(obj: Any) -> Any:
    """Convert non-JSON types for admin payloads (datetime, UUID, Decimal)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


def serialize_admin_payload(payload: dict[str, Any] | list[Any]) -> bytes:
    """Serialize admin response (dict/list) to JSON bytes.

    Handles datetime (ISO), UUID (str), Decimal (float).
    """
    return json.dumps(
        payload,
        default=_json_encoder_default,
        ensure_ascii=False,
    ).encode("utf-8")


def deserialize_admin_payload(raw: bytes) -> dict[str, Any] | list[Any]:
    """Deserialize JSON bytes to dict/list (dates remain strings)."""
    return json.loads(raw.decode("utf-8"))


class AdminCache:
    """Async Redis cache for admin responses.

    Disabled when redis_url is None or enabled=False.
    """

    def __init__(self, redis_url: str | None, enabled: bool = True) -> None:
        self._redis_url = redis_url
        self._enabled = enabled and bool(redis_url)
        self._redis: "Redis | None" = None

    def _get_redis(self) -> "Redis | None":
        """Lazy-init Redis client."""
        if self._redis is not None:
            return self._redis
        if not self._enabled or self._redis_url is None:
            return None
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(
                self._redis_url,
                decode_responses=False,
            )
            return self._redis
        except ImportError:
            logger.debug("Redis not installed, admin cache disabled")
            return None

    async def get(self, key: str) -> bytes | None:
        """Return cached value or None. Key should include prefix if desired."""
        redis = self._get_redis()
        if redis is None:
            return None
        try:
            full_key = f"{_ADMIN_CACHE_PREFIX}{key}"
            return await redis.get(full_key)
        except Exception as exc:
            logger.warning(
                "Admin cache get failed",
                extra={"key": key, "error": str(exc)},
            )
            return None

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        """Store value with TTL. No-op when cache disabled."""
        redis = self._get_redis()
        if redis is None:
            return
        try:
            full_key = f"{_ADMIN_CACHE_PREFIX}{key}"
            await redis.setex(full_key, ttl_seconds, value)
        except Exception as exc:
            logger.warning(
                "Admin cache set failed",
                extra={"key": key, "error": str(exc)},
            )
