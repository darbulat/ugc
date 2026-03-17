"""Tests for ExchangeRateService."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from ugc_bot.application.services.exchange_rate_service import (
    ExchangeRateService,
)

RATES = {"USD": Decimal("1.0"), "RUB": Decimal("90.0"), "GEL": Decimal("2.7")}


def _make_service(
    cache_rates: dict[str, Decimal] | None = None,
    provider_rates: dict[str, Decimal] | None = None,
    provider_error: Exception | None = None,
) -> tuple[ExchangeRateService, AsyncMock, AsyncMock]:
    provider = AsyncMock()
    cache = AsyncMock()
    cache.get_rates.return_value = cache_rates
    if provider_error:
        provider.fetch_rates.side_effect = provider_error
    else:
        provider.fetch_rates.return_value = provider_rates
    return ExchangeRateService(provider, cache), provider, cache


@pytest.mark.asyncio
async def test_convert_fetches_and_caches() -> None:
    """Empty cache → calls provider → caches → converts."""
    svc, provider, cache = _make_service(cache_rates=None, provider_rates=RATES)

    result = await svc.convert(Decimal("100"), "USD", "RUB")

    provider.fetch_rates.assert_awaited_once_with("USD")
    cache.set_rates.assert_awaited_once()
    assert result == Decimal("9000.00")


@pytest.mark.asyncio
async def test_convert_uses_cache() -> None:
    """Cache hit → no provider call."""
    svc, provider, _cache = _make_service(cache_rates=RATES)

    result = await svc.convert(Decimal("100"), "USD", "RUB")

    provider.fetch_rates.assert_not_awaited()
    assert result == Decimal("9000.00")


@pytest.mark.asyncio
async def test_convert_same_currency() -> None:
    """Same currency returns same amount."""
    svc, provider, cache = _make_service()

    result = await svc.convert(Decimal("42.50"), "RUB", "RUB")

    assert result == Decimal("42.50")
    provider.fetch_rates.assert_not_awaited()
    cache.get_rates.assert_not_awaited()


@pytest.mark.asyncio
async def test_convert_many() -> None:
    """Multiple currencies summed correctly."""
    svc, _provider, _cache = _make_service(cache_rates=RATES)

    amounts = {"USD": Decimal("10"), "GEL": Decimal("27")}
    result = await svc.convert_many(amounts, "RUB")

    # USD→RUB: 10 * 90 = 900
    # GEL→RUB: 27 * (90/2.7) = 27 * 33.333... = 900
    assert result == Decimal("1800.00")


@pytest.mark.asyncio
async def test_convert_returns_none_when_api_fails() -> None:
    """Provider raises → returns None."""
    svc, _provider, _cache = _make_service(
        cache_rates=None, provider_error=RuntimeError("timeout")
    )

    result = await svc.convert(Decimal("100"), "USD", "RUB")

    assert result is None


@pytest.mark.asyncio
async def test_get_rate_unknown_currency() -> None:
    """Unknown currency in rates → None."""
    svc, _, _ = _make_service(cache_rates=RATES)
    result = await svc.get_rate("USD", "XYZ")
    assert result is None


@pytest.mark.asyncio
async def test_convert_many_none_on_failure() -> None:
    """convert_many returns None if any currency fails."""
    svc, _, _ = _make_service(cache_rates=RATES)
    amounts = {
        "RUB": Decimal("100"),
        "XYZ": Decimal("50"),
    }
    result = await svc.convert_many(amounts, "USD")
    assert result is None


@pytest.mark.asyncio
async def test_close_closes_provider_session() -> None:
    """close() calls provider session close."""
    svc, provider, _ = _make_service(cache_rates=RATES)
    mock_session = AsyncMock()
    provider._session = mock_session
    await svc.close()
    mock_session.close.assert_awaited_once()
