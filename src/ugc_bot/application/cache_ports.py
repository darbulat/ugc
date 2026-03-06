"""Cache port for key-value storage with TTL (e.g. geocoder result cache)."""

from typing import Protocol


class CachePort(Protocol):
    """Async cache: get by key, set with TTL. Values are strings (e.g. JSON)."""

    async def get(self, key: str) -> str | None:
        """Return cached value or None if missing/expired."""
        ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store value with time-to-live in seconds."""
        ...
