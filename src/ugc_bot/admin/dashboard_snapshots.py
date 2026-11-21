"""Last successful dashboard values and shared refresh work."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from time import monotonic
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
        self._goals: tuple[float, Snapshot] | None = None
        self._warming: asyncio.Task[None] | None = None

    def start_warming(self, warm: Coroutine[Any, Any, None]) -> None:
        self._warming = asyncio.create_task(warm)

    def recent_goals(self) -> Snapshot | None:
        if self._goals is not None:
            calculated_at, goals = self._goals
            if monotonic() - calculated_at < 5:
                return goals
        return None

    async def goals(
        self, calculate: Callable[[], Awaitable[Snapshot]]
    ) -> Snapshot:
        recent = self.recent_goals()
        if recent is not None:
            return recent

        async def calculate_goals() -> Snapshot:
            async with asyncio.timeout(3):
                goals = await calculate()
            # Share these values with the full refresh and concurrent openings.
            self._goals = monotonic(), goals
            return goals

        return await self._share("goals", calculate_goals)

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
        return await self._share(
            task_key,
            lambda: self._refresh(key, ttl, period_date, calculate, force),
        )

    async def _share(
        self, key: str, calculate: Callable[[], Coroutine[Any, Any, Snapshot]]
    ) -> Snapshot:
        task = self._running.get(key)
        if task is None or task.done():
            task = asyncio.create_task(calculate())
            self._running[key] = task
            task.add_done_callback(
                lambda completed: self._finished(key, completed)
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
        if self._warming is not None:
            self._warming.cancel()
            await asyncio.gather(self._warming, return_exceptions=True)
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
