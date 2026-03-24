"""Tests for Redis Instagram verification repository."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import InstagramVerificationCode
from ugc_bot.infrastructure.redis_verification import (
    RedisInstagramVerificationRepository,
    _deserialize,
    _serialize,
)


def _make_code(
    user_id=None, code="ABCD1234", expires_minutes=15, used=False
) -> InstagramVerificationCode:
    now = datetime.now(timezone.utc)
    return InstagramVerificationCode(
        code_id=uuid4(),
        user_id=user_id or uuid4(),
        code=code,
        expires_at=now + timedelta(minutes=expires_minutes),
        used=used,
        created_at=now,
    )


def test_serialize_deserialize_roundtrip() -> None:
    """Serialization roundtrip preserves all fields."""
    vc = _make_code()
    data = _serialize(vc)
    restored = _deserialize(data)
    assert restored.code_id == vc.code_id
    assert restored.user_id == vc.user_id
    assert restored.code == vc.code
    assert restored.used == vc.used


@pytest.mark.asyncio
async def test_save_sets_keys_with_ttl() -> None:
    """save stores code under three keys with TTL."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    vc = _make_code()
    await repo.save(vc)

    assert mock_pipe.setex.call_count == 3
    mock_pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_expired_code_skipped() -> None:
    """save skips codes that are already expired."""
    mock_redis = MagicMock()
    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    vc = _make_code(expires_minutes=-1)
    await repo.save(vc)

    mock_redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_get_valid_code_returns_code() -> None:
    """get_valid_code returns code when found and not used."""
    vc = _make_code()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code(vc.user_id, vc.code)
    assert result is not None
    assert result.code_id == vc.code_id


@pytest.mark.asyncio
async def test_get_valid_code_returns_none_when_used() -> None:
    """get_valid_code returns None for used codes."""
    vc = _make_code(used=True)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code(vc.user_id, vc.code)
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_returns_none_when_missing() -> None:
    """get_valid_code returns None when key doesn't exist."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code(uuid4(), "XXXX")
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_by_code_returns_code() -> None:
    """get_valid_code_by_code returns code when found."""
    vc = _make_code()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code_by_code(vc.code)
    assert result is not None
    assert result.code == vc.code


@pytest.mark.asyncio
async def test_mark_used_updates_all_keys() -> None:
    """mark_used sets used=True and updates all three keys."""
    vc = _make_code()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))
    mock_redis.ttl = AsyncMock(return_value=300)
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    await repo.mark_used(vc.code_id)

    assert mock_pipe.setex.call_count == 3
    # Verify the stored payload has used=True
    stored_payload = mock_pipe.setex.call_args_list[0][0][2]
    stored = json.loads(stored_payload)
    assert stored["used"] is True


@pytest.mark.asyncio
async def test_mark_used_missing_code_is_noop() -> None:
    """mark_used does nothing if code not found in Redis."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    await repo.mark_used(uuid4())
    mock_redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_mark_used_expired_ttl_uses_default() -> None:
    """mark_used uses default TTL of 60s when key has no TTL."""
    vc = _make_code()
    mock_redis = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))
    mock_redis.ttl = AsyncMock(return_value=-1)
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    await repo.mark_used(vc.code_id)

    # Check TTL is 60 (default)
    first_setex = mock_pipe.setex.call_args_list[0][0]
    assert first_setex[1] == 60


@pytest.mark.asyncio
async def test_get_valid_code_by_code_returns_none_when_missing() -> None:
    """get_valid_code_by_code returns None when key doesn't exist."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code_by_code("XXXX")
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_by_code_returns_none_when_used() -> None:
    """get_valid_code_by_code returns None for used codes."""
    vc = _make_code(used=True)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_serialize(vc))

    repo = RedisInstagramVerificationRepository(redis_url="redis://test")
    repo._redis = mock_redis

    result = await repo.get_valid_code_by_code(vc.code)
    assert result is None


def test_get_redis_lazy_init() -> None:
    """_get_redis lazy-initializes Redis client from URL."""
    repo = RedisInstagramVerificationRepository(redis_url="redis://localhost")
    with patch("redis.asyncio.Redis") as mock_redis_cls:
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client

        result = repo._get_redis()
        assert result is mock_client
        mock_redis_cls.from_url.assert_called_once_with(
            "redis://localhost", decode_responses=True
        )

        # Second call returns cached
        result2 = repo._get_redis()
        assert result2 is mock_client
        assert mock_redis_cls.from_url.call_count == 1
