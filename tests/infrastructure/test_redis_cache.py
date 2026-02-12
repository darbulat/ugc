"""Tests for Redis-backed admin cache and serialization."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ugc_bot.infrastructure.redis_cache import (
    AdminCache,
    deserialize_admin_payload,
    serialize_admin_payload,
)


def test_serialize_deserialize_roundtrip() -> None:
    """Payload with primitives round-trips."""
    payload = {"a": 1, "b": "x", "c": [1, 2]}
    raw = serialize_admin_payload(payload)
    assert isinstance(raw, bytes)
    back = deserialize_admin_payload(raw)
    assert back == payload


def test_serialize_datetime_iso() -> None:
    """datetime is serialized as ISO string."""
    dt = datetime(2025, 2, 12, 10, 0, 0, tzinfo=timezone.utc)
    payload = {"at": dt}
    raw = serialize_admin_payload(payload)
    back = deserialize_admin_payload(raw)
    assert back["at"] == "2025-02-12T10:00:00+00:00"


def test_serialize_uuid_str() -> None:
    """UUID is serialized as string."""
    u = uuid4()
    payload = {"id": u}
    raw = serialize_admin_payload(payload)
    back = deserialize_admin_payload(raw)
    assert back["id"] == str(u)


def test_serialize_decimal_float() -> None:
    """Decimal is serialized as float."""
    payload = {"amount": Decimal("123.45")}
    raw = serialize_admin_payload(payload)
    back = deserialize_admin_payload(raw)
    assert back["amount"] == 123.45


def test_serialize_nested() -> None:
    """Nested dict/list with special types is handled."""
    u = uuid4()
    payload = {
        "items": [{"id": u, "at": datetime(2025, 1, 1, tzinfo=timezone.utc)}]
    }
    raw = serialize_admin_payload(payload)
    back = deserialize_admin_payload(raw)
    assert back["items"][0]["id"] == str(u)
    assert "2025-01-01" in back["items"][0]["at"]


@pytest.mark.asyncio
async def test_admin_cache_disabled_when_redis_url_none() -> None:
    """When redis_url is None, get returns None and set is no-op."""
    cache = AdminCache(redis_url=None)
    assert await cache.get("any") is None
    await cache.set("any", b"data", 60)
    # no raise


@pytest.mark.asyncio
async def test_admin_cache_disabled_when_enabled_false() -> None:
    """When enabled=False, get returns None and set is no-op."""
    cache = AdminCache(redis_url="redis://localhost", enabled=False)
    assert await cache.get("any") is None
    await cache.set("any", b"data", 60)


@pytest.mark.asyncio
async def test_admin_cache_get_set_ttl() -> None:
    """With mocked Redis, get returns set value and setex is called with TTL."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock(return_value=True)

    with patch.object(AdminCache, "_get_redis", return_value=mock_redis):
        cache = AdminCache(redis_url="redis://localhost")
        out = await cache.get("dashboard:today")
        assert out is None
        mock_redis.get.assert_called_once()
        call_args = mock_redis.get.call_args[0][0]
        assert call_args == "admin:cache:dashboard:today"

        await cache.set("key1", b"payload", 120)
        mock_redis.setex.assert_called_once_with(
            "admin:cache:key1", 120, b"payload"
        )


@pytest.mark.asyncio
async def test_admin_cache_get_returns_value() -> None:
    """When Redis get returns bytes, get returns them."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=b'{"a":1}')
    mock_redis.setex = AsyncMock(return_value=True)

    with patch.object(AdminCache, "_get_redis", return_value=mock_redis):
        cache = AdminCache(redis_url="redis://localhost")
        out = await cache.get("x")
        assert out == b'{"a":1}'


@pytest.mark.asyncio
async def test_admin_cache_get_exception_returns_none() -> None:
    """When Redis get raises, get returns None and logs."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))

    with patch.object(AdminCache, "_get_redis", return_value=mock_redis):
        cache = AdminCache(redis_url="redis://localhost")
        out = await cache.get("x")
        assert out is None


@pytest.mark.asyncio
async def test_admin_cache_set_exception_no_raise() -> None:
    """When Redis setex raises, set does not raise."""
    mock_redis = MagicMock()
    mock_redis.setex = AsyncMock(side_effect=ConnectionError("down"))

    with patch.object(AdminCache, "_get_redis", return_value=mock_redis):
        cache = AdminCache(redis_url="redis://localhost")
        await cache.set("x", b"data", 60)
    # no exception


@pytest.mark.asyncio
async def test_admin_cache_get_redis_returns_none_on_import_error() -> None:
    """When redis module is missing, _get_redis returns None."""
    import builtins

    original_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis.asyncio":
            raise ImportError("No module named 'redis'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        cache = AdminCache(redis_url="redis://localhost")
        result = cache._get_redis()
        assert result is None


@pytest.mark.asyncio
async def test_admin_cache_lazy_init_caches_client() -> None:
    """_get_redis is called once and client is reused."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch.object(AdminCache, "_get_redis", return_value=mock_redis):
        cache = AdminCache(redis_url="redis://localhost")
        await cache.get("a")
        await cache.get("b")
        assert mock_redis.get.call_count == 2


@pytest.mark.asyncio
async def test_admin_cache_get_redis_init_success() -> None:
    """When redis is importable, _get_redis initializes client via from_url."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock(return_value=True)
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
        cache = AdminCache(redis_url="redis://localhost:6379")
        assert cache._get_redis() is mock_redis
        assert cache._get_redis() is mock_redis
        assert mock_redis_class.from_url.call_count == 1
        mock_redis_class.from_url.assert_called_once_with(
            "redis://localhost:6379",
            decode_responses=False,
        )
