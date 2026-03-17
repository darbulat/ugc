"""Tests for exchange rate infrastructure adapters."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.infrastructure.exchange_rate import (
    OpenERApiProvider,
    RedisExchangeRateCache,
)


@pytest.mark.asyncio
async def test_open_er_api_provider_parses_response() -> None:
    """Provider correctly parses API JSON response into Decimal dict."""
    response_data = {
        "result": "success",
        "rates": {"USD": 1, "RUB": 90.5, "GEL": 2.7},
    }

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=response_data)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get.return_value = mock_cm

    provider = OpenERApiProvider(session)
    rates = await provider.fetch_rates("USD")

    assert rates["USD"] == Decimal("1")
    assert rates["RUB"] == Decimal("90.5")
    assert rates["GEL"] == Decimal("2.7")
    session.get.assert_called_once_with("https://open.er-api.com/v6/latest/USD")


@pytest.mark.asyncio
async def test_redis_cache_get_returns_none_when_empty() -> None:
    """get_rates returns None when key is missing."""
    redis = AsyncMock()
    redis.get.return_value = None

    cache = RedisExchangeRateCache(redis)
    result = await cache.get_rates("USD")

    assert result is None
    redis.get.assert_awaited_once_with("exchange_rates:USD")


@pytest.mark.asyncio
async def test_redis_cache_roundtrip() -> None:
    """set_rates stores data that get_rates can retrieve."""
    redis = AsyncMock()
    cache = RedisExchangeRateCache(redis, ttl_seconds=3600)

    rates = {"USD": Decimal("1"), "RUB": Decimal("90.0")}
    await cache.set_rates("USD", rates)

    # Capture what was stored
    call_args = redis.set.call_args
    stored_key = call_args[0][0]
    stored_value = call_args[0][1]

    assert stored_key == "exchange_rates:USD"
    assert call_args[1]["ex"] == 3600

    # Simulate get returning the stored value
    redis.get.return_value = stored_value
    result = await cache.get_rates("USD")

    assert result == {"USD": Decimal("1"), "RUB": Decimal("90.0")}


@pytest.mark.asyncio
async def test_open_er_api_provider_error_response() -> None:
    """Provider raises on non-success API result."""
    response_data = {"result": "error", "error-type": "invalid"}

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=response_data)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get.return_value = mock_cm

    provider = OpenERApiProvider(session)
    with pytest.raises(RuntimeError, match="Exchange rate API"):
        await provider.fetch_rates("INVALID")
