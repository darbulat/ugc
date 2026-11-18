"""Bounded, read-only readiness checks using the application's connections."""

import asyncio

from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

READINESS_TIMEOUT = 2.0


async def readiness_response(
    session_factory: async_sessionmaker[AsyncSession] | None,
    redis=None,
) -> JSONResponse:
    """Check required dependencies without exposing connection details."""
    if session_factory is None:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    try:
        async with asyncio.timeout(READINESS_TIMEOUT):
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            if redis is not None and not await redis.ping():
                raise ConnectionError("Redis ping failed")
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
