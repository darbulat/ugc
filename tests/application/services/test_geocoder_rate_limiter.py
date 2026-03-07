"""Tests for RateLimitedGeocoder."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.geocoder_rate_limiter import (
    RateLimitedGeocoder,
)


@pytest.fixture
def mock_delegate() -> GeocoderPort:
    """GeocoderPort mock that returns fixed results and records calls."""
    delegate = MagicMock(spec=GeocoderPort)
    delegate.geocode = AsyncMock(return_value=(55.75, 37.62))
    delegate.geocode_with_details = AsyncMock(
        return_value=(
            55.75,
            37.62,
            "place",
            "city",
            "Moscow",
            "Russia",
        )
    )
    delegate.reverse_geocode = AsyncMock(
        return_value=("Moscow", "Moscow", "Russia")
    )
    delegate.get_multipolygon_wkt_for_queries = AsyncMock(
        return_value="MULTIPOLYGON(((37 55, 38 55, 38 56, 37 56, 37 55)))"
    )
    delegate.accepts_as_populated_place = MagicMock(return_value=True)
    delegate.accepts_as_place_or_region = MagicMock(return_value=True)
    return delegate


@pytest.mark.asyncio
async def test_rate_limited_geocoder_delegates_geocode(
    mock_delegate: GeocoderPort,
) -> None:
    """geocode passes through to delegate and returns result."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    result = await limiter.geocode("Moscow", region=None, country="Russia")
    assert result == (55.75, 37.62)
    mock_delegate.geocode.assert_called_once_with(
        "Moscow", region=None, country="Russia"
    )


@pytest.mark.asyncio
async def test_rate_limited_geocoder_delegates_geocode_with_details(
    mock_delegate: GeocoderPort,
) -> None:
    """geocode_with_details passes through to delegate."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    result = await limiter.geocode_with_details("Moscow")
    assert result == (55.75, 37.62, "place", "city", "Moscow", "Russia")
    mock_delegate.geocode_with_details.assert_called_once_with(
        "Moscow", region=None, country=None
    )


@pytest.mark.asyncio
async def test_rate_limited_geocoder_delegates_reverse_geocode(
    mock_delegate: GeocoderPort,
) -> None:
    """reverse_geocode passes through to delegate."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    result = await limiter.reverse_geocode(55.75, 37.62)
    assert result == ("Moscow", "Moscow", "Russia")
    mock_delegate.reverse_geocode.assert_called_once_with(55.75, 37.62)


@pytest.mark.asyncio
async def test_rate_limited_geocoder_delegates_get_multipolygon(
    mock_delegate: GeocoderPort,
) -> None:
    """get_multipolygon_wkt_for_queries passes through to delegate."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    queries = [("Moscow", None, "Russia")]
    result = await limiter.get_multipolygon_wkt_for_queries(queries)
    assert result is not None
    assert "MULTIPOLYGON" in result
    mock_delegate.get_multipolygon_wkt_for_queries.assert_called_once_with(
        queries
    )


def test_rate_limited_geocoder_delegates_accepts_as_populated_place(
    mock_delegate: GeocoderPort,
) -> None:
    """accepts_as_populated_place passes through to delegate."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    assert limiter.accepts_as_populated_place("place", "city") is True
    mock_delegate.accepts_as_populated_place.assert_called_once_with(
        "place", "city"
    )


def test_rate_limited_geocoder_delegates_accepts_as_place_or_region(
    mock_delegate: GeocoderPort,
) -> None:
    """accepts_as_place_or_region passes through to delegate."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    assert (
        limiter.accepts_as_place_or_region("boundary", "administrative") is True
    )
    mock_delegate.accepts_as_place_or_region.assert_called_once_with(
        "boundary", "administrative"
    )


@pytest.mark.asyncio
async def test_rate_limited_geocoder_enforces_delay_between_calls(
    mock_delegate: GeocoderPort,
) -> None:
    """Two consecutive async calls are spaced by at least delay_seconds."""
    delay = 0.15
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=delay)
    t0 = time.monotonic()
    await limiter.geocode("Moscow")
    await limiter.geocode("Kazan")
    elapsed = time.monotonic() - t0
    assert elapsed >= delay
    assert mock_delegate.geocode.call_count == 2


@pytest.mark.asyncio
async def test_rate_limited_geocoder_zero_delay_no_wait(
    mock_delegate: GeocoderPort,
) -> None:
    """With delay_seconds=0, no artificial wait between calls."""
    limiter = RateLimitedGeocoder(delegate=mock_delegate, delay_seconds=0)
    t0 = time.monotonic()
    await limiter.geocode("Moscow")
    await limiter.geocode("Kazan")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1
    assert mock_delegate.geocode.call_count == 2
