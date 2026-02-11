"""Geography parsing and matching for order-to-blogger filtering."""

import re
from dataclasses import dataclass
from typing import Literal

from ugc_bot.application.region_cities_data import (
    REGION_TO_CITIES,
)

GeographyType = Literal["world", "country", "region", "cities"]

WORLD_PHRASES = frozenset(
    {"весь мир", "мир", "world", "вся планета", "планета", "глобально"}
)
COUNTRY_PHRASES = frozenset(
    {"рф", "россия", "russia", "вся россия", "вся рф", "по всей россии"}
)

GEO_TOKEN_SPLIT_RE = re.compile(r"[,/]+|\s+и\s+|\n+")


def _normalize_token(value: str) -> str:
    """Normalize a single geography token for comparison."""
    s = (value or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("ё", "е")
    return s.strip()


def normalize_geo_token(value: str) -> str:
    """Normalize a single geography token (strip, lower, ё→е)."""
    return _normalize_token(value)


def parse_geography(raw: str | None) -> "GeographySpec | None":
    """
    Parse order geography string into a structured spec.

    Returns None for empty/whitespace input. Otherwise returns GeographySpec
    with type world | country | region | cities and normalized values.
    """
    if raw is None:
        return None
    text = (raw or "").strip()
    if not text:
        return None

    normalized_full = _normalize_token(text)

    if normalized_full in WORLD_PHRASES:
        return GeographySpec(type="world", values=[])

    if normalized_full in COUNTRY_PHRASES:
        return GeographySpec(type="country", values=[])

    parts = GEO_TOKEN_SPLIT_RE.split(text)
    tokens = [_normalize_token(p) for p in parts if _normalize_token(p)]

    if not tokens:
        return None

    if len(tokens) == 1 and tokens[0] in REGION_TO_CITIES:
        return GeographySpec(type="region", values=tokens)

    return GeographySpec(type="cities", values=tokens)


@dataclass(frozen=True)
class GeographySpec:
    """Parsed geography requirement for an order."""

    type: GeographyType
    values: list[str]


def _audience_tokens(audience_geo: str | None) -> list[str]:
    """Split audience_geo into normalized tokens."""
    if not audience_geo:
        return []
    return [
        _normalize_token(p)
        for p in GEO_TOKEN_SPLIT_RE.split(audience_geo)
        if _normalize_token(p)
    ]


def _matches_cities(
    city_norm: str,
    values: list[str],
    audience_geo: str | None,
) -> bool:
    """Return True if city or any audience token is in values."""
    if city_norm and city_norm in values:
        return True
    return any(token in values for token in _audience_tokens(audience_geo))


def _matches_region(
    city_norm: str,
    region_key: str,
    audience_geo: str | None,
) -> bool:
    """Return True if city or audience matches region or its cities."""
    region_cities = REGION_TO_CITIES.get(region_key)
    if region_cities is None:
        return False
    if city_norm == region_key or city_norm in region_cities:
        return True
    for token in _audience_tokens(audience_geo):
        if token == region_key or token in region_cities:
            return True
    return False


def blogger_matches_geography(
    blogger_city: str,
    spec: GeographySpec,
    *,
    audience_geo: str | None = None,
) -> bool:
    """
    Check if blogger city (and optionally audience_geo) matches order geography.

    Uses normalization (lower, ё→е) and exact match. For region type uses
    REGION_TO_CITIES; matches if city is in region's city list or equals region.
    """
    if spec.type == "world" or spec.type == "country":
        return True

    city_norm = _normalize_token(blogger_city or "")

    if spec.type == "cities":
        if not city_norm and not _audience_tokens(audience_geo):
            return False
        return _matches_cities(city_norm, spec.values, audience_geo)

    if spec.type == "region":
        if not spec.values:
            return False
        return _matches_region(city_norm, spec.values[0], audience_geo)

    return False
