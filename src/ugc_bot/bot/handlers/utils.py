"""Shared helpers for bot handlers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass(slots=True)
class RateLimiter:
    """Simple in-memory rate limiter."""

    limit: int
    window_seconds: float
    _events: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, key: str) -> bool:
        """Return True when request is allowed."""

        now = monotonic()
        window_start = now - self.window_seconds
        events = [ts for ts in self._events.get(key, []) if ts >= window_start]
        if len(events) >= self.limit:
            self._events[key] = events
            return False
        events.append(now)
        self._events[key] = events
        return True


async def send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    retries: int,
    delay_seconds: float,
    logger: logging.Logger,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a message with retry on failures."""

    for attempt in range(1, retries + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except Exception as exc:  # pragma: no cover - depends on network errors
            logger.warning(
                "Send message failed",
                extra={
                    "attempt": attempt,
                    "retries": retries,
                    "chat_id": chat_id,
                    "error": str(exc),
                    **(extra or {}),
                },
            )
            if attempt < retries:
                await asyncio.sleep(delay_seconds)
    return False
