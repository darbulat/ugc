"""Tests for Instagram stats provider wrappers."""

from unittest.mock import AsyncMock, patch

import pytest

from ugc_bot.application.ports import RapidApiRateLimitError
from ugc_bot.infrastructure.instagram.stats_provider_wrappers import (
    MultiProviderInstagramStatsClient,
    SingleProviderWrapper,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInstagramRapidApiClient,
)


@pytest.mark.asyncio
async def test_single_provider_wrapper_returns_data_and_provider_id() -> None:
    """SingleProviderWrapper returns (data, provider_id)."""
    raw = {"data": {"username": "x"}}
    inner = InMemoryInstagramRapidApiClient(
        profile_by_username={"x": raw},
    )
    client = SingleProviderWrapper(inner, "my_provider")
    data, provider = await client.get_profile_stats_with_provider("x")
    assert data == raw
    assert provider == "my_provider"


@pytest.mark.asyncio
async def test_multi_provider_fallback_on_429() -> None:
    """MultiProviderInstagramStatsClient tries next provider on 429."""

    class RateLimitClient(InMemoryInstagramRapidApiClient):
        async def get_profile_stats_by_username(self, username: str):
            raise RapidApiRateLimitError("429")

    ok_data = {"data": {"username": "jane"}}
    clients: list = [
        (RateLimitClient(), "first"),
        (
            InMemoryInstagramRapidApiClient(
                profile_by_username={"jane": ok_data},
            ),
            "second",
        ),
    ]
    multi = MultiProviderInstagramStatsClient(clients, fallback_delay_seconds=0)
    data, provider = await multi.get_profile_stats_with_provider("jane")
    assert data == ok_data
    assert provider == "second"


@pytest.mark.asyncio
async def test_multi_provider_sleeps_after_429_before_next() -> None:
    """After 429, client waits random delay before trying next provider."""

    class RateLimitClient(InMemoryInstagramRapidApiClient):
        async def get_profile_stats_by_username(self, username: str):
            raise RapidApiRateLimitError("429")

    ok_data = {"data": {"username": "jane"}}
    clients: list = [
        (RateLimitClient(), "first"),
        (
            InMemoryInstagramRapidApiClient(
                profile_by_username={"jane": ok_data},
            ),
            "second",
        ),
    ]
    with patch(
        "ugc_bot.infrastructure.instagram.stats_provider_wrappers.asyncio.sleep",  # noqa: E501
        new_callable=AsyncMock,
    ) as mock_sleep:
        multi = MultiProviderInstagramStatsClient(
            clients, fallback_delay_seconds=3.0
        )
        data, provider = await multi.get_profile_stats_with_provider("jane")
    mock_sleep.assert_awaited_once()
    (delay,) = mock_sleep.call_args[0]
    # random_delay_seconds(3.0) is in [3*0.6, 3*1.6] = [1.8, 4.8], min 0.1
    assert 1.8 <= delay <= 4.8
    assert data == ok_data
    assert provider == "second"


@pytest.mark.asyncio
async def test_multi_provider_all_rate_limited_returns_none() -> None:
    """When all providers are rate limited, returns (None, last_provider_id)."""

    class RateLimitClient(InMemoryInstagramRapidApiClient):
        async def get_profile_stats_by_username(self, username: str):
            raise RapidApiRateLimitError("429")

    clients: list = [
        (RateLimitClient(), "first"),
        (RateLimitClient(), "second"),
    ]
    multi = MultiProviderInstagramStatsClient(clients, fallback_delay_seconds=0)
    data, provider = await multi.get_profile_stats_with_provider("jane")
    assert data is None
    assert provider == "second"
