"""Tests for RedisInstagramVerificationRepository."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import InstagramVerificationCode
from ugc_bot.infrastructure.redis_verification_repository import (
    RedisInstagramVerificationRepository,
    _deserialize,
    _serialize,
)


def _make_code(
    *, used: bool = False, expired: bool = False
) -> InstagramVerificationCode:
    now = datetime.now(timezone.utc)
    delta = timedelta(minutes=-5) if expired else timedelta(minutes=10)
    return InstagramVerificationCode(
        code_id=uuid4(),
        user_id=uuid4(),
        code="TEST123",
        expires_at=now + delta,
        used=used,
        created_at=now,
    )


def test_serialize_deserialize_roundtrip() -> None:
    code = _make_code()
    raw = _serialize(code)
    restored = _deserialize(raw)
    assert restored.code_id == code.code_id
    assert restored.user_id == code.user_id
    assert restored.code == code.code
    assert restored.used == code.used


@pytest.mark.asyncio
async def test_save_sets_three_keys() -> None:
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipe
    repo._redis = mock_redis

    code = _make_code()
    await repo.save(code)

    assert mock_pipe.setex.call_count == 3
    mock_pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_valid_code_returns_entity() -> None:
    code = _make_code()
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = _serialize(code)
    repo._redis = mock_redis

    result = await repo.get_valid_code(code.user_id, code.code)
    assert result is not None
    assert result.code_id == code.code_id


@pytest.mark.asyncio
async def test_get_valid_code_returns_none_if_missing() -> None:
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    repo._redis = mock_redis

    result = await repo.get_valid_code(uuid4(), "NOPE")
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_returns_none_if_expired() -> None:
    code = _make_code(expired=True)
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = _serialize(code)
    repo._redis = mock_redis

    result = await repo.get_valid_code(code.user_id, code.code)
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_returns_none_if_used() -> None:
    code = _make_code(used=True)
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = _serialize(code)
    repo._redis = mock_redis

    result = await repo.get_valid_code(code.user_id, code.code)
    assert result is None


@pytest.mark.asyncio
async def test_get_valid_code_by_code_returns_entity() -> None:
    code = _make_code()
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = _serialize(code)
    repo._redis = mock_redis

    result = await repo.get_valid_code_by_code(code.code)
    assert result is not None
    assert result.code == code.code


@pytest.mark.asyncio
async def test_get_valid_code_by_code_returns_none_if_missing() -> None:
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    repo._redis = mock_redis

    result = await repo.get_valid_code_by_code("NOPE")
    assert result is None


@pytest.mark.asyncio
async def test_mark_used_deletes_three_keys() -> None:
    code = _make_code()
    id_data = json.dumps({"code": code.code, "user_id": str(code.user_id)})
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=id_data)
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()
    mock_redis.pipeline.return_value = mock_pipe
    repo._redis = mock_redis

    await repo.mark_used(code.code_id)

    assert mock_pipe.delete.call_count == 3
    mock_pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_used_noop_when_not_found() -> None:
    repo = RedisInstagramVerificationRepository(redis_url="redis://fake")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    repo._redis = mock_redis

    await repo.mark_used(uuid4())
    mock_redis.pipeline.assert_not_called()
