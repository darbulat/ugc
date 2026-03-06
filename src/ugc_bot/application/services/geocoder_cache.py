"""Caching wrapper for GeocoderPort: cache key building and serialization."""

import hashlib
import json
from typing import Any, List, Optional, Tuple

from ugc_bot.application.cache_ports import CachePort
from ugc_bot.application.ports import GeocoderPort

_KEY_PREFIX = "geocoder:"
_NULL_PLACEHOLDER = "__null__"


def _normalize_query_args(
    query: str, region: Optional[str], country: Optional[str]
) -> List[Any]:
    """Normalize geocode/geocode_with_details arguments for cache key."""
    return [
        (query or "").strip(),
        (region or "").strip() if region is not None else None,
        (country or "").strip() if country is not None else None,
    ]


def _normalize_coords(lat: float, lon: float) -> List[float]:
    """Normalize coordinates to 5 decimal places for cache key."""
    return [round(lat, 5), round(lon, 5)]


def _normalize_queries(
    queries: List[Tuple[str, Optional[str], str]],
) -> List[Tuple[str, str, str]]:
    """Normalize query list: strip and use empty string for None region."""
    return [
        (
            (q or "").strip(),
            (r or "").strip() if r is not None else "",
            (c or "").strip() if c else "",
        )
        for q, r, c in queries
    ]


def _hash_args(args: Any) -> str:
    """Stable short hash of normalized args."""
    payload = json.dumps(args, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_cache_key_geocode(
    query: str, region: Optional[str], country: str
) -> str:
    """Build cache key for geocode(query, region, country)."""
    h = _hash_args(_normalize_query_args(query, region, country))
    return f"{_KEY_PREFIX}geocode:{h}"


def build_cache_key_geocode_with_details(
    query: str, region: Optional[str], country: Optional[str]
) -> str:
    """Build cache key for geocode_with_details(query, region, country)."""
    h = _hash_args(_normalize_query_args(query, region, country))
    return f"{_KEY_PREFIX}geocode_with_details:{h}"


def build_cache_key_reverse(lat: float, lon: float) -> str:
    """Build cache key for reverse_geocode(lat, lon)."""
    h = _hash_args(_normalize_coords(lat, lon))
    return f"{_KEY_PREFIX}reverse:{h}"


def build_cache_key_multipolygon(
    queries: List[Tuple[str, Optional[str], str]],
) -> str:
    """Build cache key for get_multipolygon_wkt_for_queries(queries)."""
    normalized = sorted(_normalize_queries(queries))
    h = _hash_args(normalized)
    return f"{_KEY_PREFIX}multipolygon:{h}"


# --- Serialize / deserialize ---


def serialize_geocode_result(result: Optional[Tuple[float, float]]) -> str:
    """Serialize geocode result for cache: [lat, lon] or null."""
    if result is None:
        return json.dumps(None)
    return json.dumps([result[0], result[1]])


def deserialize_geocode_result(raw: str) -> Optional[Tuple[float, float]]:
    """Deserialize cached geocode result."""
    data = json.loads(raw)
    if data is None:
        return None
    return (float(data[0]), float(data[1]))


def serialize_geocode_with_details_result(
    result: Optional[
        Tuple[float, float, str, str, Optional[str], Optional[str]]
    ],
) -> str:
    """Serialize geocode_with_details result for cache."""
    if result is None:
        return json.dumps(None)
    lat, lon, pc, pt, reg, cnt = result
    return json.dumps(
        [
            lat,
            lon,
            pc,
            pt,
            reg if reg is not None else _NULL_PLACEHOLDER,
            cnt if cnt is not None else _NULL_PLACEHOLDER,
        ]
    )


def deserialize_geocode_with_details_result(
    raw: str,
) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
    """Deserialize cached geocode_with_details result."""
    data = json.loads(raw)
    if data is None:
        return None
    reg = data[4] if data[4] != _NULL_PLACEHOLDER else None
    cnt = data[5] if data[5] != _NULL_PLACEHOLDER else None
    return (
        float(data[0]),
        float(data[1]),
        str(data[2]),
        str(data[3]),
        reg,
        cnt,
    )


def serialize_reverse_geocode_result(
    result: Optional[Tuple[str, Optional[str], Optional[str]]],
) -> str:
    """Serialize reverse_geocode result for cache."""
    if result is None:
        return json.dumps(None)
    city, region, country = result
    return json.dumps(
        [
            city,
            region if region is not None else _NULL_PLACEHOLDER,
            country if country is not None else _NULL_PLACEHOLDER,
        ]
    )


def deserialize_reverse_geocode_result(
    raw: str,
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """Deserialize cached reverse_geocode result."""
    data = json.loads(raw)
    if data is None:
        return None
    region = data[1] if data[1] != _NULL_PLACEHOLDER else None
    country = data[2] if data[2] != _NULL_PLACEHOLDER else None
    return (str(data[0]), region, country)


def serialize_multipolygon_result(result: Optional[str]) -> str:
    """Serialize get_multipolygon_wkt_for_queries result (WKT string)."""
    if result is None:
        return json.dumps(None)
    return json.dumps(result)


def deserialize_multipolygon_result(raw: str) -> Optional[str]:
    """Deserialize cached multipolygon WKT result."""
    data = json.loads(raw)
    if data is None:
        return None
    return str(data)


# --- CachingGeocoder ---


class CachingGeocoder:
    """GeocoderPort wrapper that caches async method results."""

    def __init__(
        self,
        delegate: GeocoderPort,
        cache: CachePort,
        ttl_seconds: int,
        cache_negative: bool = True,
    ) -> None:
        self._delegate = delegate
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._cache_negative = cache_negative

    def accepts_as_populated_place(
        self, place_class: str, place_type: str
    ) -> bool:
        """Delegate to underlying geocoder (no cache)."""
        return self._delegate.accepts_as_populated_place(
            place_class, place_type
        )

    def accepts_as_place_or_region(
        self, place_class: str, place_type: str
    ) -> bool:
        """Delegate to underlying geocoder (no cache)."""
        return self._delegate.accepts_as_place_or_region(
            place_class, place_type
        )

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[float, float]]:
        """Geocode with cache; on miss delegate and store result."""
        key = build_cache_key_geocode(query, region, country)
        cached = await self._cache.get(key)
        if cached is not None:
            return deserialize_geocode_result(cached)
        result = await self._delegate.geocode(query, region, country)
        if result is not None or self._cache_negative:
            await self._cache.set(
                key,
                serialize_geocode_result(result),
                self._ttl_seconds,
            )
        return result

    async def geocode_with_details(
        self,
        query: str,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
        """Geocode with details; on miss delegate and store result."""
        key = build_cache_key_geocode_with_details(query, region, country)
        cached = await self._cache.get(key)
        if cached is not None:
            return deserialize_geocode_with_details_result(cached)
        result = await self._delegate.geocode_with_details(
            query, region, country
        )
        if result is not None or self._cache_negative:
            await self._cache.set(
                key,
                serialize_geocode_with_details_result(result),
                self._ttl_seconds,
            )
        return result

    async def reverse_geocode(
        self, lat: float, lon: float
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Reverse geocode; on miss delegate and store result."""
        key = build_cache_key_reverse(lat, lon)
        cached = await self._cache.get(key)
        if cached is not None:
            return deserialize_reverse_geocode_result(cached)
        result = await self._delegate.reverse_geocode(lat, lon)
        if result is not None or self._cache_negative:
            await self._cache.set(
                key,
                serialize_reverse_geocode_result(result),
                self._ttl_seconds,
            )
        return result

    async def get_multipolygon_wkt_for_queries(
        self,
        queries: List[Tuple[str, Optional[str], str]],
    ) -> Optional[str]:
        """Resolve queries to WKT; on miss delegate and store result."""
        key = build_cache_key_multipolygon(queries)
        cached = await self._cache.get(key)
        if cached is not None:
            return deserialize_multipolygon_result(cached)
        result = await self._delegate.get_multipolygon_wkt_for_queries(queries)
        if result is not None or self._cache_negative:
            await self._cache.set(
                key,
                serialize_multipolygon_result(result),
                self._ttl_seconds,
            )
        return result
