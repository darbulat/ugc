"""Tests for MaxRedisStateStore."""

import json
from unittest.mock import AsyncMock

import pytest

from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore


@pytest.fixture
def redis_mock():
    return AsyncMock()


@pytest.fixture
def store(redis_mock):
    return MaxRedisStateStore(redis_mock, chat_id="c1", user_id="u1")


@pytest.mark.asyncio
async def test_get_state_returns_string(store, redis_mock):
    redis_mock.get = AsyncMock(return_value="some_state")
    assert await store.get_state() == "some_state"


@pytest.mark.asyncio
async def test_get_state_returns_none_when_missing(store, redis_mock):
    redis_mock.get = AsyncMock(return_value=None)
    assert await store.get_state() is None


@pytest.mark.asyncio
async def test_get_state_decodes_bytes(store, redis_mock):
    redis_mock.get = AsyncMock(return_value=b"some_state")
    assert await store.get_state() == "some_state"


@pytest.mark.asyncio
async def test_get_data_returns_dict(store, redis_mock):
    redis_mock.get = AsyncMock(return_value=json.dumps({"k": "v"}))
    assert await store.get_data() == {"k": "v"}


@pytest.mark.asyncio
async def test_get_data_returns_empty_on_missing(store, redis_mock):
    redis_mock.get = AsyncMock(return_value=None)
    assert await store.get_data() == {}


@pytest.mark.asyncio
async def test_get_data_clears_corrupted_key(store, redis_mock):
    redis_mock.get = AsyncMock(return_value="not json{{{")
    result = await store.get_data()
    assert result == {}
    redis_mock.delete.assert_called_once()


@pytest.mark.asyncio
async def test_set_state(store, redis_mock):
    await store.set_state("new_state")
    redis_mock.set.assert_called_once()


@pytest.mark.asyncio
async def test_set_state_none_deletes(store, redis_mock):
    await store.set_state(None)
    redis_mock.delete.assert_called_once()


@pytest.mark.asyncio
async def test_update_data(store, redis_mock):
    redis_mock.get = AsyncMock(return_value=json.dumps({"a": 1}))
    await store.update_data(b=2)
    redis_mock.set.assert_called_once()
    saved = json.loads(redis_mock.set.call_args[0][1])
    assert saved == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_clear(store, redis_mock):
    await store.clear()
    redis_mock.delete.assert_called_once()
