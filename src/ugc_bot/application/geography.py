"""Geography parsing and matching for order-to-blogger filtering.

Order.geography: free-text place(s) or "whole world". No in-code dictionaries
for countries/regions; geocoder (Nominatim) is the single source of truth.
Cities are arbitrary worldwide.
"""

import re
from dataclasses import dataclass
from typing import Literal

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


def get_regions_for_city(city: str) -> list[str]:
    """Return region keys that contain this city (for disambiguation).

    No hardcoded dictionary: always returns empty list. Region is resolved
    by geocoder when needed.
    """
    _ = city
    return []


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
    Return cities list for Mini App city picker.

    No hardcoded dictionary: cities are arbitrary worldwide. Returns empty
    list; use free-text city input or map/location picker instead.
    """
    return []


def resolve_region_from_city_field(
    city_raw: str | None,
) -> tuple[str | None, Literal["ok", "multiple", "unrecognized"]]:
    """
    Parse blogger profile city field and resolve to region key.

    No hardcoded dictionary: region is resolved by geocoder only. Always
    returns (None, "unrecognized"); callers should use geocoder for region.
    """
    if not city_raw or not city_raw.strip():
        return (None, "unrecognized")
    return (None, "unrecognized")
