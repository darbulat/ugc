"""Tests for CachingGeocoder and geocoder cache serialization."""

import json
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.services.geocoder_cache import (
    CachingGeocoder,
    build_cache_key_geocode,
    build_cache_key_multipolygon,
    build_cache_key_reverse,
    deserialize_geocode_result,
    deserialize_geocode_with_details_result,
    deserialize_multipolygon_result,
    deserialize_reverse_geocode_result,
    serialize_geocode_result,
    serialize_geocode_with_details_result,
    serialize_multipolygon_result,
    serialize_reverse_geocode_result,
)

# --- Cache key stability ---


def test_build_cache_key_geocode_stable() -> None:
    """Same query/region/country produce same key; whitespace normalized."""
    k1 = build_cache_key_geocode(" Moscow ", "MO", "Russia")
    k2 = build_cache_key_geocode("Moscow", "MO", "Russia")
    assert k1 == k2
    assert k1.startswith("geocoder:geocode:")


def test_build_cache_key_reverse_stable() -> None:
    """Same coords (rounded to 5 decimals) produce same key."""
    k1 = build_cache_key_reverse(55.751234, 37.617890)
    k2 = build_cache_key_reverse(55.75123, 37.61789)
    assert k1 == k2
    assert k1.startswith("geocoder:reverse:")


def test_build_cache_key_multipolygon_stable() -> None:
    """Same queries list (sorted) produce same key."""
    q1 = [("Moscow", None, "RU"), ("Spb", "Leningrad", "RU")]
    q2 = [("Spb", "Leningrad", "RU"), ("Moscow", None, "RU")]
    assert build_cache_key_multipolygon(q1) == build_cache_key_multipolygon(q2)
    assert build_cache_key_multipolygon(q1).startswith("geocoder:multipolygon:")


# --- Serialization round-trips ---


def test_serialize_deserialize_geocode_result() -> None:
    """geocode result round-trip: tuple and None."""
    assert deserialize_geocode_result(serialize_geocode_result(None)) is None
    t = (55.75, 37.62)
    assert deserialize_geocode_result(serialize_geocode_result(t)) == t


def test_serialize_deserialize_geocode_with_details_result() -> None:
    """geocode_with_details result round-trip: full tuple and None."""
    assert (
        deserialize_geocode_with_details_result(
            serialize_geocode_with_details_result(None)
        )
        is None
    )
    t: Tuple[float, float, str, str, Optional[str], Optional[str]] = (
        55.75,
        37.62,
        "place",
        "city",
        "Moscow",
        "Russia",
    )
    assert (
        deserialize_geocode_with_details_result(
            serialize_geocode_with_details_result(t)
        )
        == t
    )
    t_none_region = (55.75, 37.62, "place", "city", None, "Russia")
    assert (
        deserialize_geocode_with_details_result(
            serialize_geocode_with_details_result(t_none_region)
        )
        == t_none_region
    )


def test_serialize_deserialize_reverse_geocode_result() -> None:
    """reverse_geocode result round-trip: tuple and None."""
    assert (
        deserialize_reverse_geocode_result(
            serialize_reverse_geocode_result(None)
        )
        is None
    )
    t: Tuple[str, Optional[str], Optional[str]] = ("Moscow", "MO", "Russia")
    assert (
        deserialize_reverse_geocode_result(serialize_reverse_geocode_result(t))
        == t
    )
    t_none = ("Moscow", None, None)
    assert (
        deserialize_reverse_geocode_result(
            serialize_reverse_geocode_result(t_none)
        )
        == t_none
    )


def test_serialize_deserialize_multipolygon_result() -> None:
    """get_multipolygon_wkt result round-trip: WKT string and None."""
    assert (
        deserialize_multipolygon_result(serialize_multipolygon_result(None))
        is None
    )
    wkt = (
        "MULTIPOLYGON(((37.6 55.75,37.7 55.75,37.7 55.76,"
        "37.6 55.76,37.6 55.75)))"
    )
    assert (
        deserialize_multipolygon_result(serialize_multipolygon_result(wkt))
        == wkt
    )


# --- CachingGeocoder: cache miss -> delegate + set ---


@pytest.mark.asyncio
async def test_caching_geocoder_geocode_miss_then_delegate_and_set() -> None:
    """On cache miss, delegate.geocode is called and result is stored."""
    delegate = MagicMock()
    delegate.geocode = AsyncMock(return_value=(55.75, 37.62))
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.geocode("Moscow", None, "Russia")
    assert result == (55.75, 37.62)
    cache.get.assert_called_once()
    delegate.geocode.assert_called_once_with("Moscow", None, "Russia")
    cache.set.assert_called_once()
    call_args = cache.set.call_args[0]
    assert call_args[0].startswith("geocoder:geocode:")
    assert "55.75" in call_args[1] and "37.62" in call_args[1]
    assert call_args[2] == 3600


@pytest.mark.asyncio
async def test_caching_geocoder_geocode_hit_no_delegate() -> None:
    """On cache hit, delegate is not called and cached value returned."""
    delegate = MagicMock()
    delegate.geocode = AsyncMock()
    cache = MagicMock()
    cache.get = AsyncMock(return_value="[55.75, 37.62]")
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.geocode("Moscow", region=None, country="Russia")
    assert result == (55.75, 37.62)
    cache.get.assert_called_once()
    delegate.geocode.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_caching_geocoder_geocode_with_details_hit() -> None:
    """On cache hit for geocode_with_details, delegate not called."""
    delegate = MagicMock()
    delegate.geocode_with_details = AsyncMock()
    cached_val = '[55.75, 37.62, "place", "city", "MO", "Russia"]'
    cache = MagicMock()
    cache.get = AsyncMock(return_value=cached_val)
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.geocode_with_details("Moscow", None, "Russia")
    assert result == (55.75, 37.62, "place", "city", "MO", "Russia")
    delegate.geocode_with_details.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_caching_geocoder_reverse_geocode_hit() -> None:
    """On cache hit for reverse_geocode, delegate not called."""
    delegate = MagicMock()
    delegate.reverse_geocode = AsyncMock()
    cache = MagicMock()
    cache.get = AsyncMock(return_value='["Moscow", "MO", "Russia"]')
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.reverse_geocode(55.75, 37.62)
    assert result == ("Moscow", "MO", "Russia")
    delegate.reverse_geocode.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_caching_geocoder_multipolygon_hit() -> None:
    """On cache hit for multipolygon WKT, delegate not called."""
    delegate = MagicMock()
    delegate.get_multipolygon_wkt_for_queries = AsyncMock()
    wkt = "MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))"
    cache = MagicMock()
    cache.get = AsyncMock(return_value=json.dumps(wkt))
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    queries: List[Tuple[str, Optional[str], str]] = [("Moscow", None, "RU")]
    result = await wrapper.get_multipolygon_wkt_for_queries(queries)
    assert result == wkt
    delegate.get_multipolygon_wkt_for_queries.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_caching_geocoder_geocode_with_details_miss() -> None:
    """On miss, geocode_with_details calls delegate and caches result."""
    delegate = MagicMock()
    delegate.geocode_with_details = AsyncMock(
        return_value=(55.75, 37.62, "place", "city", "MO", "Russia")
    )
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.geocode_with_details("Moscow", None, "Russia")
    assert result == (55.75, 37.62, "place", "city", "MO", "Russia")
    delegate.geocode_with_details.assert_called_once()
    cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_caching_geocoder_reverse_geocode_miss() -> None:
    """On miss, reverse_geocode calls delegate and caches result."""
    delegate = MagicMock()
    delegate.reverse_geocode = AsyncMock(
        return_value=("Moscow", "MO", "Russia")
    )
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    result = await wrapper.reverse_geocode(55.75, 37.62)
    assert result == ("Moscow", "MO", "Russia")
    delegate.reverse_geocode.assert_called_once_with(55.75, 37.62)
    cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_caching_geocoder_multipolygon_miss() -> None:
    """On miss, get_multipolygon_wkt_for_queries calls delegate and caches."""
    delegate = MagicMock()
    wkt = "MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))"
    delegate.get_multipolygon_wkt_for_queries = AsyncMock(return_value=wkt)
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    queries: List[Tuple[str, Optional[str], str]] = [("Moscow", None, "RU")]
    result = await wrapper.get_multipolygon_wkt_for_queries(queries)
    assert result == wkt
    delegate.get_multipolygon_wkt_for_queries.assert_called_once_with(queries)
    cache.set.assert_called_once()


@pytest.mark.asyncio
async def test_caching_geocoder_accepts_delegate_only() -> None:
    """accepts_* methods delegate to underlying geocoder, no cache."""
    delegate = MagicMock()
    delegate.accepts_as_populated_place = MagicMock(return_value=True)
    delegate.accepts_as_place_or_region = MagicMock(return_value=False)
    cache = MagicMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    assert wrapper.accepts_as_populated_place("place", "city") is True
    assert wrapper.accepts_as_place_or_region("boundary", "admin") is False
    delegate.accepts_as_populated_place.assert_called_once_with("place", "city")
    delegate.accepts_as_place_or_region.assert_called_once_with(
        "boundary", "admin"
    )
    cache.get.assert_not_called()
    cache.set.assert_not_called()


@pytest.mark.asyncio
async def test_caching_geocoder_caches_none_when_cache_negative_true() -> None:
    """When cache_negative=True, None result is stored and later returned."""
    delegate = MagicMock()
    delegate.geocode = AsyncMock(return_value=None)
    cache = MagicMock()
    cache.get = AsyncMock(side_effect=[None, "null"])
    cache.set = AsyncMock()
    wrapper = CachingGeocoder(
        delegate=delegate,
        cache=cache,
        ttl_seconds=3600,
        cache_negative=True,
    )
    r1 = await wrapper.geocode("NonExistentCity123", None, "Russia")
    assert r1 is None
    cache.set.assert_called_once()
    delegate.geocode.assert_called_once()
    delegate.reset_mock()
    cache.get = AsyncMock(return_value="null")
    r2 = await wrapper.geocode("NonExistentCity123", None, "Russia")
    assert r2 is None
    delegate.geocode.assert_not_called()
