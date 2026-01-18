"""Site customization to shim aioredis for fastapi-admin."""

from __future__ import annotations

import sys
import types
from typing import Any, cast


redis_asyncio: Any = None
try:
    from redis import asyncio as _redis_asyncio  # type: ignore[import-untyped]

    redis_asyncio = cast(Any, _redis_asyncio)
except Exception:  # pragma: no cover - redis may be unavailable
    redis_asyncio = None


if redis_asyncio is not None and "aioredis" not in sys.modules:
    shim = types.ModuleType("aioredis")
    shim.Redis = redis_asyncio.Redis  # type: ignore[attr-defined]
    shim.StrictRedis = redis_asyncio.Redis  # type: ignore[attr-defined]
    shim.from_url = redis_asyncio.from_url  # type: ignore[attr-defined]
    sys.modules["aioredis"] = shim
