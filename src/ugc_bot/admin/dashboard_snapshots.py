"""Last successful dashboard values, refreshed only when a visitor asks."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from ugc_bot.infrastructure.redis_cache import (
    AdminCache,
    deserialize_admin_payload,
    serialize_admin_payload,
)

logger = logging.getLogger(__name__)
Snapshot = dict[str, Any]
_RETENTION_SECONDS = 7 * 86400


def _version(saved: Snapshot) -> tuple[datetime, datetime]:
    calculated = datetime.fromisoformat(saved["calculated_at"])
    counts = datetime.fromisoformat(saved["counts_at"])
    if calculated.tzinfo is None or counts.tzinfo is None:
        raise ValueError("Snapshot timestamp has no timezone")
    return calculated, counts


def _decode(raw: bytes) -> Snapshot:
    saved = deserialize_admin_payload(raw)
    if (
        not isinstance(saved, dict)
        or not all(
            isinstance(saved.get(name), dict)
            for name in ("payload", "creator_base", "attention_counts")
        )
        or not all(
            isinstance(saved.get(name), str)
            for name in ("calculated_at", "counts_at")
        )
    ):
        raise ValueError("Invalid dashboard snapshot")
    if (
        datetime.now(timezone.utc) - _version(saved)[0]
    ).total_seconds() > _RETENTION_SECONDS:
        raise ValueError("Snapshot has expired")
    return saved


class DashboardSnapshots:
    """Persist good values and share refreshes in an admin worker."""

    def __init__(self, cache: AdminCache | None) -> None:
        self.cache = cache
        self._last: dict[str, Snapshot] = {}
        self._running: dict[str, asyncio.Task[Snapshot]] = {}

    async def read(self, key: str) -> Snapshot | None:
        if self.cache is not None:
            try:
                async with asyncio.timeout(0.25):
                    raw = await self.cache.get(f"dashboard-snapshot:v1:{key}")
                if raw is not None:
                    saved = _decode(raw)
                    local = self._last.get(key)
                    if local is None or _version(saved) >= _version(local):
                        self._last[key] = saved
            except (TimeoutError, TypeError, ValueError):
                pass
        last = self._last.get(key)
        if last is not None:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(
                    last["calculated_at"]
                )
                if age.total_seconds() <= _RETENTION_SECONDS:
                    return last
            except (TypeError, ValueError):
                pass
        return None

    async def refresh(
        self,
        key: str,
        ttl: int,
        period_date: str,
        calculate: Callable[[Snapshot | None], Awaitable[Snapshot]],
        *,
        force: bool = False,
    ) -> Snapshot:
        task_key = f"{key}:diagnostics" if force else key
        task = self._running.get(task_key)
        if task is None or task.done():
            task = asyncio.create_task(
                self._refresh(key, ttl, period_date, calculate, force)
            )
            self._running[task_key] = task
            task.add_done_callback(
                lambda completed: self._finished(task_key, completed)
            )
        # Leaving the page must not cancel the result needed by other visitors.
        return await asyncio.shield(task)

    def _finished(self, key: str, task: asyncio.Task[Snapshot]) -> None:
        if self._running.get(key) is task:
            self._running.pop(key)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.warning(
                "Dashboard refresh failed",
                extra={"period": key, "error_type": type(error).__name__},
            )

    async def _refresh(
        self, key, ttl, period_date, calculate, force
    ) -> Snapshot:
        async with asyncio.timeout(20):
            previous = await self.read(key)
            marker = None
            if self.cache is not None and not force:
                try:
                    async with asyncio.timeout(0.25):
                        marker = await self.cache.get(
                            f"dashboard:snapshot-fresh:v1:{key}"
                        )
                except TimeoutError:
                    pass
            reusable = (
                previous is not None
                and not force
                and previous.get("period_date") == period_date
                and marker == previous["calculated_at"].encode()
                and (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(previous["calculated_at"])
                ).total_seconds()
                < ttl
            )
            result = await calculate(previous if reusable else None)
            if not force:
                self._last[key] = result
                if self.cache is not None:
                    try:
                        async with asyncio.timeout(0.25):
                            await self.cache.set(
                                f"dashboard-snapshot:v1:{key}",
                                serialize_admin_payload(result),
                                _RETENTION_SECONDS,
                            )
                            if not reusable:
                                await self.cache.set(
                                    f"dashboard:snapshot-fresh:v1:{key}",
                                    result["calculated_at"].encode(),
                                    ttl,
                                )
                    except TimeoutError:
                        pass
            return result

    async def close(self) -> None:
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
