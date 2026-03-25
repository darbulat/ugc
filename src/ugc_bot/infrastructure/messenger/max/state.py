"""MaxRedisStateStore — Redis-backed FSM state storage for Max messenger."""

import json
from typing import Any

from redis.asyncio import Redis


class MaxRedisStateStore:
    """Redis-backed state store for Max messenger conversational flows."""

    _STATE_KEY_PREFIX = "max:state:"
    _DATA_KEY_PREFIX = "max:data:"
    _TTL_SECONDS = 86400  # 24 hours

    def __init__(self, redis: Redis, chat_id: str, user_id: str) -> None:
        self._redis = redis
        self._state_key = f"{self._STATE_KEY_PREFIX}{chat_id}:{user_id}"
        self._data_key = f"{self._DATA_KEY_PREFIX}{chat_id}:{user_id}"

    async def get_state(self) -> str | None:
        """Return current state name."""
        value = await self._redis.get(self._state_key)
        return value if isinstance(value, str) else None

    async def set_state(self, state: str | None) -> None:
        """Set current state name (None clears)."""
        if state is None:
            await self._redis.delete(self._state_key)
        else:
            await self._redis.setex(self._state_key, self._TTL_SECONDS, state)

    async def update_data(self, **kwargs: Any) -> None:
        """Update state data with provided kwargs."""
        existing = await self.get_data()
        existing.update(kwargs)
        await self._redis.setex(
            self._data_key, self._TTL_SECONDS, json.dumps(existing)
        )

    async def get_data(self) -> dict[str, Any]:
        """Return state data."""
        raw = await self._redis.get(self._data_key)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    async def clear(self) -> None:
        """Clear state and data."""
        await self._redis.delete(self._state_key, self._data_key)
