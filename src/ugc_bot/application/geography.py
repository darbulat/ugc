"""Geography parsing and matching for order-to-blogger filtering.

Order.geography: free-text place(s) or "whole world". No in-code dictionaries
for countries/regions; geocoder (Nominatim) is the single source of truth.
"""

import re
from dataclasses import dataclass
from typing import Literal

from ugc_bot.application.region_cities_data import (
    REGION_ALIASES,
    REGION_TO_CITIES,
)

GeographyType = Literal["world", "places"]

WORLD_PHRASES = frozenset(
    {"весь мир", "мир", "world", "вся планета", "планета", "глобально"}
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
    Parse Order.geography into a spec: "world" or list of place tokens.

    No dictionary lookup. Whole-world phrases -> type world. Everything else
    -> split by separators, normalize, type places. Geocoder resolves later.
    Returns None for empty/whitespace input.
    """
    if raw is None:
        return None
    text = (raw or "").strip()
    if not text:
        return None

    normalized_full = _normalize_token(text)
    if normalized_full in WORLD_PHRASES:
        return GeographySpec(type="world", values=[])

    parts = GEO_TOKEN_SPLIT_RE.split(text)
    tokens = [_normalize_token(p) for p in parts if _normalize_token(p)]
    if not tokens:
        return None

    return GeographySpec(type="places", values=tokens)


@dataclass(frozen=True)
class GeographySpec:
    """Parsed geography requirement for an order."""

    type: GeographyType
    values: list[str]


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


def get_geometry_queries_from_spec(
    spec: "GeographySpec",
) -> list[tuple[str, str | None, str]]:
    """Build list of (query, region, country) for geocoder to resolve polygons.

    World -> empty list. Places -> each value as (query, None, "") for
    global Nominatim search (no country hint).
    """
    if spec.type == "world":
        return []
    if spec.type == "places" and spec.values:
        return [(val, None, "") for val in spec.values]
    return []


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
        seen.update(REGION_ALIASES)
        _CANONICAL_CITIES_SET = frozenset(seen)
    return _CANONICAL_CITIES_SET


def is_canonical_city(city: str) -> bool:
    """Return True if normalized city is in the canonical cities dictionary."""
    normalized = _normalize_token(city)
    return normalized in get_canonical_cities_set()


def is_canonical_city_only(value: str) -> bool:
    """True if value is a city from the dictionary, not a region name."""
    normalized = _normalize_token(value)
    return normalized in _get_city_to_regions()


def resolve_region_from_city_field(
    city_raw: str | None,
) -> tuple[str | None, Literal["ok", "multiple", "unrecognized"]]:
    """
    Parse blogger profile city field (may contain "City", "Region, City" or
    "City, Region") and resolve to a single region key for profile.region.

    Returns (region_key, status):
    - ("region_key", "ok"): one region resolved; store region_key.
    - (None, "multiple"): city is in several regions; caller should log.
    - (None, "unrecognized"): unrecognized city; caller should log.
    """
    if not city_raw or not city_raw.strip():
        return (None, "unrecognized")
    tokens = [
        _normalize_token(p)
        for p in GEO_TOKEN_SPLIT_RE.split(city_raw)
        if _normalize_token(p)
    ]
    if not tokens:
        return (None, "unrecognized")

    def is_region(t: str) -> bool:
        canonical = REGION_ALIASES.get(t, t)
        return canonical in REGION_TO_CITIES

    def is_city(t: str) -> bool:
        return bool(get_regions_for_city(t))

    city_tokens = [t for t in tokens if is_city(t)]
    region_tokens = [t for t in tokens if is_region(t)]

    primary_city = city_tokens[0] if city_tokens else None
    if not primary_city:
        return (None, "unrecognized")

    for r in region_tokens:
        canonical_region = REGION_ALIASES.get(r, r)
        cities_in_region = REGION_TO_CITIES.get(canonical_region, [])
        if primary_city in cities_in_region:
            return (canonical_region, "ok")

    regions = get_regions_for_city(primary_city)
    if len(regions) == 1:
        return (regions[0], "ok")
    if len(regions) > 1:
        return (None, "multiple")
    return (None, "unrecognized")
