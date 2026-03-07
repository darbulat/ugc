"""In-memory TTL cache backend for geocoder results (CachePort)."""

import time
from collections import OrderedDict
from threading import Lock
from typing import Optional


class GeocoderCacheMemory:
    """In-memory cache with TTL and optional max size (FIFO eviction)."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self._max_entries = max_entries
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = Lock()

    def _evict_expired(self, now: float) -> None:
        """Remove expired entries (oldest first)."""
        expired = [k for k, (_, expiry) in self._store.items() if expiry <= now]
        for k in expired:
            self._store.pop(k, None)

    def _evict_if_over_capacity(self) -> None:
        """Remove oldest entry if at capacity (by insert order)."""
        while len(self._store) > self._max_entries and self._store:
            self._store.popitem(last=False)

    async def get(self, key: str) -> Optional[str]:
        """Return cached value or None if missing/expired."""
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if expiry <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store value with TTL; evict oldest if over max_entries."""
        now = time.monotonic()
        expiry = now + ttl_seconds
        with self._lock:
            self._evict_expired(now)
            self._store[key] = (value, expiry)
            self._store.move_to_end(key)
            self._evict_if_over_capacity()
