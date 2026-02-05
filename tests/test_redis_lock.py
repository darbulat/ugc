"""Tests for Redis-based lock manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.redis_lock import IssueDescriptionLockManager


@pytest.mark.asyncio
async def test_lock_memory_fallback_when_no_redis_url() -> None:
    """When redis_url is None, use in-memory lock."""
    manager = IssueDescriptionLockManager(redis_url=None)
    entered = []

    async with manager.lock("user123"):
        entered.append(1)

    assert entered == [1]


@pytest.mark.asyncio
async def test_lock_memory_serializes_concurrent_calls_per_user() -> None:
    """In-memory lock serializes concurrent access per user (u1 tasks sequential)."""
    manager = IssueDescriptionLockManager(redis_url=None)
    order: list[str] = []

    async def slow_task(user_id: str) -> None:
        async with manager.lock(user_id):
            order.append(f"start_{user_id}")
            await asyncio.sleep(0.02)
            order.append(f"end_{user_id}")

    await asyncio.gather(
        slow_task("u1"),
        slow_task("u1"),
    )

    assert order[0] == "start_u1"
    assert order[1] == "end_u1"
    assert order[2] == "start_u1"
    assert order[3] == "end_u1"


@pytest.mark.asyncio
async def test_lock_redis_path_when_redis_available() -> None:
    """When Redis is available, use Redis lock."""
    mock_lock = AsyncMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.lock = MagicMock(return_value=mock_lock)

    with patch.object(
        IssueDescriptionLockManager, "_get_redis", return_value=mock_redis
    ):
        manager = IssueDescriptionLockManager(redis_url="redis://localhost")
        async with manager.lock("user99"):
            pass
        async with manager.lock("user99"):
            pass

    assert mock_redis.lock.call_count == 2
    call_args = mock_redis.lock.call_args
    assert "ugc:lock:issue_desc:user99" in str(call_args)
    assert call_args[1].get("timeout") == 30


@pytest.mark.asyncio
async def test_lock_redis_failure_falls_back_to_memory() -> None:
    """When Redis lock raises, fall back to in-memory lock."""
    mock_lock = AsyncMock()
    mock_lock.__aenter__ = AsyncMock(side_effect=ConnectionError("Redis down"))
    mock_lock.__aexit__ = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.lock = MagicMock(return_value=mock_lock)

    with patch.object(
        IssueDescriptionLockManager, "_get_redis", return_value=mock_redis
    ):
        manager = IssueDescriptionLockManager(redis_url="redis://localhost")
        entered = []
        async with manager.lock("user1"):
            entered.append(1)

    assert entered == [1]


@pytest.mark.asyncio
async def test_get_redis_returns_none_on_import_error() -> None:
    """When Redis import fails, _get_redis returns None."""
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "redis.asyncio":
            raise ImportError("No module named 'redis'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        manager = IssueDescriptionLockManager(redis_url="redis://localhost")
        result = manager._get_redis()
        assert result is None


@pytest.mark.asyncio
async def test_get_redis_lazy_init_success() -> None:
    """When Redis is available, _get_redis returns client and caches it."""
    mock_redis = MagicMock()
    mock_redis_class = MagicMock()
    mock_redis_class.from_url = MagicMock(return_value=mock_redis)

    fake_redis_asyncio = MagicMock()
    fake_redis_asyncio.Redis = mock_redis_class
    fake_redis = MagicMock()
    fake_redis.asyncio = fake_redis_asyncio

    with patch.dict(
        "sys.modules",
        {"redis": fake_redis, "redis.asyncio": fake_redis_asyncio},
        clear=False,
    ):
        manager = IssueDescriptionLockManager(redis_url="redis://localhost:6379")
        result1 = manager._get_redis()
        result2 = manager._get_redis()
        assert result1 is mock_redis
        assert result2 is mock_redis
        assert mock_redis_class.from_url.call_count == 1
        mock_redis_class.from_url.assert_called_once_with(
            "redis://localhost:6379", decode_responses=True
        )
