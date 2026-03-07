"""Geocoding service: resolve city/address to coordinates (lat, lon)."""

import logging
from typing import Any, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_POPULATED_PLACE_TYPES: frozenset[str] = frozenset(
    {
        "city",
        "town",
        "village",
        "hamlet",
        "locality",
        "suburb",
        "neighbourhood",
        "quarter",
        "isolated_dwelling",
    }
)

_NOMINATIM_PLACE_OR_REGION_TYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("place", "city"),
        ("place", "town"),
        ("place", "village"),
        ("place", "hamlet"),
        ("place", "suburb"),
        ("place", "neighbourhood"),
        ("place", "locality"),
        ("place", "isolated_dwelling"),
        # Regions/countries are often returned either as place/country or as
        # administrative boundaries.
        ("place", "country"),
        ("boundary", "administrative"),
    }
)


def _normalize_place_token(value: str) -> str:
    """Normalize provider place class/type tokens for comparisons."""
    return (value or "").strip().lower()


def _geojson_geometry_to_wkt(geojson: dict[str, Any]) -> Optional[str]:
    """Convert GeoJSON geometry to WKT (SRID 4326, lon lat order).

    Supports Polygon and MultiPolygon. Returns None for Point or invalid input.
    """
    if not isinstance(geojson, dict):
        return None
    geom_type = geojson.get("type")
    coords = geojson.get("coordinates")
    if not coords:
        return None
    if geom_type == "Polygon":
        # coordinates: [exterior_ring, ...hole_rings]; ring = [[lon, lat], ...]
        rings = coords
        if not rings or not rings[0]:
            return None
        exterior = rings[0]
        pts = ", ".join(f"{c[0]} {c[1]}" for c in exterior)
        return f"POLYGON(({pts}))"
    if geom_type == "MultiPolygon":
        # MultiPolygon: list of [exterior_ring, holes]; ring = [[lon, lat], ...]
        polygons = []
        for poly in coords:
            if not poly or not poly[0]:
                continue
            exterior = poly[0]
            pts = ", ".join(f"{c[0]} {c[1]}" for c in exterior)
            polygons.append(f"(({pts}))")
        if not polygons:
            return None
        return "MULTIPOLYGON(" + ",".join(polygons) + ")"
    return None


def _extract_one_polygon_from_wkt(s: str, parts: List[str]) -> None:
    """Append polygon part(s) from one WKT string to parts list."""
    s = s.strip().upper()
    if s.startswith("POLYGON(("):
        # POLYGON((x y, ...)) -> need "((x y, ...))" for MULTIPOLYGON
        # s[9:-2] is "x y, ..." (drop the "))" at end)
        coords = s[9:-2].strip()
        if coords:
            parts.append("((" + coords + "))")
    elif s.startswith("MULTIPOLYGON("):
        inner = s[13:-1].strip()
        depth = 0
        start = -1
        for i, ch in enumerate(inner):
            if ch == "(":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and start >= 0:
                    parts.append(inner[start : i + 1])


def wkt_multipolygon_from_polygon_wkts(wkt_list: List[str]) -> Optional[str]:
    """Merge POLYGON/MULTIPOLYGON WKT strings into one MULTIPOLYGON WKT."""
    if not wkt_list:
        return None
    parts: List[str] = []
    for wkt in wkt_list:
        if wkt and wkt.strip():
            _extract_one_polygon_from_wkt(wkt, parts)
    if not parts:
        return None
    return "MULTIPOLYGON(" + ",".join(parts) + ")"


def wkt_multipoint_from_lat_lon(lat: float, lon: float) -> str:
    """Build WKT MULTIPOINT for one point (SRID 4326: lon, lat order)."""
    return f"MULTIPOINT(({lon} {lat}))"


def wkt_multipoint_from_coords(coords: List[Tuple[float, float]]) -> str:
    """Build WKT MULTIPOINT from list of (lat, lon) (SRID 4326: lon, lat)."""
    if not coords:
        return ""
    points = ",".join(f"({lon} {lat})" for lat, lon in coords)
    return f"MULTIPOINT({points})"


def wkt_point_from_lat_lon(lat: float, lon: float) -> str:
    """Build WKT POINT (SRID 4326: lon, lat order)."""
    return f"POINT({lon} {lat})"


def _extract_region_from_address(address: object) -> Optional[str]:
    """Extract region from Nominatim address (state/state_district/county)."""
    if not isinstance(address, dict):
        return None
    for key in ("state", "state_district", "county"):
        val = address.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_country_from_address(address: object) -> Optional[str]:
    """Extract country from Nominatim address dict."""
    if not isinstance(address, dict):
        return None
    val = address.get("country")
    if val and isinstance(val, str) and val.strip():
        return val.strip()
    return None


class NominatimGeocoder:
    """Geocoder using OpenStreetMap Nominatim API (no API key)."""

    def __init__(
        self,
        base_url: str = "https://nominatim.openstreetmap.org",
        user_agent: str = "ugc-bot/1.0",
        timeout_seconds: float = 5.0,
        enabled: bool = True,
    ):
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._enabled = enabled

    def accepts_as_populated_place(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when Nominatim class/type represent a populated place."""
        cls = _normalize_place_token(place_class)
        typ = _normalize_place_token(place_type)
        return cls == "place" and typ in _NOMINATIM_POPULATED_PLACE_TYPES

    def accepts_as_place_or_region(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when Nominatim class/type represent place or region."""
        cls = _normalize_place_token(place_class)
        typ = _normalize_place_token(place_type)
        return (cls, typ) in _NOMINATIM_PLACE_OR_REGION_TYPES

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[float, float]]:
        """Return (latitude, longitude) for the query, or None if not found."""
        if not self._enabled or not (query or "").strip():
            return None
        q = query.strip()
        country_str = (country or "Russia").strip()
        if region and region.strip():
            q = f"{q}, {region.strip()}, {country_str}"
        else:
            q = f"{q}, {country_str}"
        url = f"{self._base_url}/search"
        logger.info("geocoder request: GET %s q=%r", url, q)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            ) as client:
                resp = await client.get(
                    url,
                    params={"q": q, "format": "json", "limit": 1},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not data or not isinstance(data, list):
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        lat_s = first.get("lat")
        lon_s = first.get("lon")
        if lat_s is None or lon_s is None:
            return None
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except (TypeError, ValueError):
            return None
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return (lat, lon)
        return None

    async def geocode_with_details(
        self,
        query: str,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
        """Return (lat, lon, osm_class, osm_type, region, country) or None.

        region/country from address (addressdetails=1). No default country:
        when country is empty, query is sent without country.
        """
        if not self._enabled or not (query or "").strip():
            return None
        q = query.strip()
        parts: list[str] = [q]
        if region and region.strip():
            parts.append(region.strip())
        country_str = (country or "").strip()
        if country_str:
            parts.append(country_str)
        q = ", ".join(parts)
        url = f"{self._base_url}/search"
        logger.info("geocoder request: GET %s q=%r addressdetails=1", url, q)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "en",
                },
            ) as client:
                resp = await client.get(
                    url,
                    params={
                        "q": q,
                        "format": "json",
                        "limit": 1,
                        "addressdetails": 1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not data or not isinstance(data, list):
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        lat_s = first.get("lat")
        lon_s = first.get("lon")
        if lat_s is None or lon_s is None:
            return None
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        osm_class = (first.get("class") or first.get("category") or "").strip()
        osm_type = (first.get("type") or "").strip()
        address = first.get("address")
        region_from_nominatim = _extract_region_from_address(address)
        country_from_nominatim = _extract_country_from_address(address)
        return (
            lat,
            lon,
            osm_class,
            osm_type,
            region_from_nominatim,
            country_from_nominatim,
        )

    async def _search_osm_id(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[str, int]]:
        """Return (osm_type_letter, osm_id) for lookup, or None.

        osm_type_letter is one of N (node), W (way), R (relation).
        When country is None or empty, query is sent without country (global).
        """
        if not self._enabled or not (query or "").strip():
            return None
        parts: List[str] = [query.strip()]
        if region and region.strip():
            parts.append(region.strip())
        if country and country.strip():
            parts.append(country.strip())
        q = ", ".join(parts)
        url = f"{self._base_url}/search"
        logger.info("geocoder request: GET %s q=%r (osm_id lookup)", url, q)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            ) as client:
                resp = await client.get(
                    url,
                    params={"q": q, "format": "json", "limit": 1},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not data or not isinstance(data, list):
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        osm_type = (first.get("osm_type") or "").strip().upper()
        osm_id_raw = first.get("osm_id")
        if osm_id_raw is None:
            return None
        try:
            osm_id = int(osm_id_raw)
        except (TypeError, ValueError):
            return None
        type_letter = osm_type[0] if osm_type else "R"
        if type_letter not in ("N", "W", "R"):
            type_letter = "R"
        return (type_letter, osm_id)

    async def get_polygon_wkt(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[str]:
        """Return WKT POLYGON or MULTIPOLYGON for the place, or None.

        Uses Nominatim search + lookup with polygon_geojson=1.
        """
        osm = await self._search_osm_id(query, region, country)
        if not osm:
            return None
        type_letter, osm_id = osm
        osm_ids_param = f"{type_letter}{osm_id}"
        url = f"{self._base_url}/lookup"
        logger.info(
            "geocoder request: GET %s osm_ids=%s polygon_geojson=1",
            url,
            osm_ids_param,
        )
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            ) as client:
                resp = await client.get(
                    url,
                    params={
                        "osm_ids": osm_ids_param,
                        "polygon_geojson": 1,
                        "format": "geojson",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        features = data.get("features")
        if not features or not isinstance(features, list):
            return None
        first = features[0]
        if not isinstance(first, dict):
            return None
        geometry = first.get("geometry")
        if not isinstance(geometry, dict):
            return None
        return _geojson_geometry_to_wkt(geometry)

    async def get_multipolygon_wkt_for_queries(
        self,
        queries: List[Tuple[str, Optional[str], str]],
    ) -> Optional[str]:
        """Resolve multiple (query, region, country) to one MULTIPOLYGON WKT.

        Each tuple is (query, region_or_None, country). Empty country means
        global Nominatim search. None country defaults to Russia.
        """
        wkt_parts: List[str] = []
        for query, region, country in queries:
            if not (query or "").strip():
                continue
            country_param = country if country is not None else "Russia"
            wkt = await self.get_polygon_wkt(
                query.strip(),
                region,
                country_param,
            )
            if wkt:
                wkt_parts.append(wkt)
        return wkt_multipolygon_from_polygon_wkts(wkt_parts)

    async def reverse_geocode(
        self, lat: float, lon: float
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Return (city, region, country) for coordinates, or None if not found.

        Uses Nominatim reverse API. Prefers city/town/village from address.
        """
        if not self._enabled:
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        url = f"{self._base_url}/reverse"
        logger.info("geocoder request: GET %s lat=%s lon=%s", url, lat, lon)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "ru",
                },
            ) as client:
                resp = await client.get(
                    url,
                    params={
                        "lat": lat,
                        "lon": lon,
                        "format": "json",
                        "addressdetails": 1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        address = data.get("address")
        if not isinstance(address, dict):
            return None
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("county")
        )
        if isinstance(city, dict):
            city = city.get("name")
        if not city or not isinstance(city, str) or not city.strip():
            return None
        region = _extract_region_from_address(address)
        country = _extract_country_from_address(address)
        return (city.strip(), region, country)
