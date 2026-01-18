"""Compatibility shim for fastapi-admin on Python 3.13."""

from __future__ import annotations

from redis.asyncio import Redis, StrictRedis, from_url

__all__ = ["Redis", "StrictRedis", "from_url"]
