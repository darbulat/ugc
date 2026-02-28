"""Geography parsing and matching for order-to-blogger filtering.

Order.geography stores the advertiser's answer to:
"В каких городах или регионах может находиться креатор? Можно указать
от 1 до 10 городов, регионы или написать «РФ». Нужно для бартерных
заказов и доставки продукта."
"""

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
    Parse Order.geography (advertiser: cities/regions/РФ) into a spec.

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


def _parse_city_tokens(city_raw: str | None) -> list[str]:
    """
    Split city string into normalized tokens.

    Field city may contain several cities (e.g. comma or " и " separated).
    Returns list of normalized tokens for matching against order geography.
    """
    text = (city_raw or "").strip()
    if not text:
        return []
    return [
        _normalize_token(p)
        for p in GEO_TOKEN_SPLIT_RE.split(text)
        if _normalize_token(p)
    ]


def _matches_cities(blogger_city_tokens: list[str], values: list[str]) -> bool:
    """
    Return True if any blogger city matches any value.

    values may contain both city names and region names (from REGION_TO_CITIES).
    For a region, match if blogger's city is in that region's city list.
    """
    for token in blogger_city_tokens:
        for val in values:
            if val in REGION_TO_CITIES:
                if _matches_region([token], val):
                    return True
            elif token == val:
                return True
    return False


def _matches_region(
    blogger_city_tokens: list[str],
    region_key: str,
) -> bool:
    """Return True if any blogger city matches region or its cities."""
    region_cities = REGION_TO_CITIES.get(region_key)
    if region_cities is None:
        return False
    for token in blogger_city_tokens:
        if token == region_key or token in region_cities:
            return True
    return False


def _canonical_to_label(canonical: str) -> str:
    """Convert canonical city id (lowercase) to display label (title case)."""
    if not canonical:
        return ""
    parts = re.split(r"[\s\-]+", canonical)
    return " ".join(p.capitalize() for p in parts)


_CITY_TO_REGIONS: dict[str, list[str]] | None = None


def _get_city_to_regions() -> dict[str, list[str]]:
    """Build reverse map: city -> list of region keys where city appears."""
    global _CITY_TO_REGIONS
    if _CITY_TO_REGIONS is None:
        result: dict[str, list[str]] = {}
        for region_key, cities in REGION_TO_CITIES.items():
            for city in cities:
                result.setdefault(city, []).append(region_key)
        _CITY_TO_REGIONS = result
    return _CITY_TO_REGIONS


def get_regions_for_city(city: str) -> list[str]:
    """Return region keys that contain this city (for disambiguation)."""
    normalized = _normalize_token(city)
    return list(_get_city_to_regions().get(normalized, []))


def region_key_to_label(region_key: str) -> str:
    """Return display label for region key (e.g. for inline buttons)."""
    return _canonical_to_label(region_key)


def parse_miniapp_city_id(raw_id: str) -> tuple[str, str | None]:
    """
    Parse Mini App city id into (canonical_city, region_key or None).

    Id format is "region:city" or plain "city". Returns normalized city and
    region (if present).
    """
    if not raw_id or not raw_id.strip():
        return ("", None)
    s = raw_id.strip()
    if ":" in s:
        parts = s.split(":", 1)
        region = _normalize_token(parts[0]) or None
        city = _normalize_token(parts[1]) if len(parts) > 1 else ""
        return (city, region)
    return (_normalize_token(s), None)


def get_cities_list_for_miniapp() -> list[dict[str, str]]:
    """
    Build cities list for Mini App; id region:city, label includes region.

    For cities in multiple regions returns several entries with id "region:city"
    and label "City (Region)". For cities in one region one entry with same
    format. Deduplicates (region, city) pairs, sorted by label.
    """
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, str]] = []
    for region_key, cities in REGION_TO_CITIES.items():
        region_label = _canonical_to_label(region_key)
        for city in cities:
            pair = (region_key, city)
            if pair in seen:
                continue
            seen.add(pair)
            city_label = _canonical_to_label(city)
            label = f"{city_label} ({region_label})"
            items.append({"id": f"{region_key}:{city}", "label": label})
    items.sort(key=lambda x: x["label"])
    return items


_CANONICAL_CITIES_SET: frozenset[str] | None = None


def get_canonical_cities_set() -> frozenset[str]:
    """Return set of valid canonical city ids (for validation)."""
    global _CANONICAL_CITIES_SET
    if _CANONICAL_CITIES_SET is None:
        seen: set[str] = set()
        for key, cities in REGION_TO_CITIES.items():
            seen.add(key)
            seen.update(cities)
        _CANONICAL_CITIES_SET = frozenset(seen)
    return _CANONICAL_CITIES_SET


def is_canonical_city(city: str) -> bool:
    """Return True if normalized city is in the canonical cities dictionary."""
    normalized = _normalize_token(city)
    return normalized in get_canonical_cities_set()


def blogger_matches_geography(blogger_city: str, spec: GeographySpec) -> bool:
    """
    Check if blogger city matches order geography.

    blogger_city may contain several cities (comma or " и " separated).
    If any of them matches Order.geography, returns True.
    Uses normalization (lower, ё→е). For region type uses REGION_TO_CITIES.
    """
    if spec.type == "world" or spec.type == "country":
        return True

    city_tokens = _parse_city_tokens(blogger_city)
    if not city_tokens:
        return False

    if spec.type == "cities":
        return _matches_cities(city_tokens, spec.values)

    if spec.type == "region":
        if not spec.values:
            return False
        return _matches_region(city_tokens, spec.values[0])

    return False
