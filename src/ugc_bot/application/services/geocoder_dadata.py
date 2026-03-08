"""Geocoding service implementation for Dadata Suggestions API."""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


def _normalize_place_token(value: str) -> str:
    """Normalize provider place class/type tokens for comparisons."""
    return (value or "").strip().lower()


@dataclass(slots=True)
class DadataGeocoder:
    """Geocoder using Dadata Suggestions API.

    This implementation focuses on city/address -> coordinates. Dadata does not
    provide polygons compatible with our MULTIPOLYGON use-cases, so polygon
    methods currently return None.
    """

    base_url: str = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"
    api_key: str = ""
    secret: str = ""
    timeout_seconds: float = 5.0
    enabled: bool = True

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        if self.secret:
            headers["X-Secret"] = self.secret
        return headers

    def _build_query(
        self, query: str, region: Optional[str], country: Optional[str]
    ) -> str:
        """Build a free-text query string for suggestions API."""
        q = (query or "").strip()
        if region and region.strip():
            q = f"{q}, {region.strip()}"
        if country and country.strip():
            q = f"{q}, {country.strip()}"
        return q

    async def _post_json(self, url: str, payload: dict) -> Optional[dict]:
        """POST JSON and return response dict, or None on any error."""
        logger.info(
            "geocoder request: POST %s payload=%s",
            url,
            {k: v for k, v in payload.items()},
        )
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, headers=self._headers()
            ) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _get_first_suggestion_data(
        self, data: Optional[dict]
    ) -> Optional[dict]:
        """Extract suggestions[0].data dict from Dadata response."""
        if not isinstance(data, dict):
            return None
        suggestions = data.get("suggestions")
        if not suggestions or not isinstance(suggestions, list):
            return None
        first = suggestions[0]
        if not isinstance(first, dict):
            return None
        d = first.get("data")
        return d if isinstance(d, dict) else None

    def _parse_lat_lon(self, d: dict) -> Optional[Tuple[float, float]]:
        """Parse geo_lat/geo_lon from suggestion data."""
        lat_s = d.get("geo_lat")
        lon_s = d.get("geo_lon")
        if lat_s is None or lon_s is None:
            return None
        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return (lat, lon)

    def accepts_as_populated_place(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when place_class/type represent a populated place.

        For Dadata we encode:
        - place_class: 'fias'
        - place_type: data.fias_level (string)
        """
        cls = _normalize_place_token(place_class)
        typ = _normalize_place_token(place_type)
        # FIAS levels vary by dataset; 4=city, 6=settlement are common.
        return cls == "fias" and typ in {"4", "6"}

    def accepts_as_place_or_region(
        self, place_class: str, place_type: str
    ) -> bool:
        """Return True when place_class/type represent a place or a region."""
        cls = _normalize_place_token(place_class)
        typ = _normalize_place_token(place_type)
        # Accept regions + cities + settlements; reject streets/houses.
        return cls == "fias" and typ in {"1", "3", "4", "5", "6"}

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[float, float]]:
        """Return (latitude, longitude) for the query, or None if not found."""
        details = await self.geocode_with_details(
            query, region=region, country=country
        )
        if details is None:
            return None
        lat, lon, *_ = details
        return (lat, lon)

    async def geocode_with_details(
        self,
        query: str,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
        """Return (lat, lon, place_class, place_type, region, country) or None.

        place_class/type are provider-specific.
        """
        if not self.enabled or not (query or "").strip():
            return None
        if not self.api_key:
            return None

        url = f"{self.base_url.rstrip('/')}/suggest/address"
        payload = {
            "query": self._build_query(query, region, country),
            "count": 1,
        }
        data = await self._post_json(url, payload)
        d = self._get_first_suggestion_data(data)
        if d is None:
            return None

        coords = self._parse_lat_lon(d)
        if coords is None:
            return None
        lat, lon = coords

        fias_level = d.get("fias_level")
        place_type = str(fias_level) if fias_level is not None else ""
        region_name = (
            d.get("region") if isinstance(d.get("region"), str) else None
        )
        country_name = (
            d.get("country") if isinstance(d.get("country"), str) else None
        )

        return (lat, lon, "fias", place_type, region_name, country_name)

    async def get_multipolygon_wkt_for_queries(
        self,
        queries: List[Tuple[str, Optional[str], str]],
    ) -> Optional[str]:
        """Resolve queries to one MULTIPOLYGON WKT (not supported by Dadata)."""
        return None

    async def reverse_geocode(
        self, lat: float, lon: float
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Reverse geocode coordinates to (city, region, country) or None."""
        if not self.enabled or not self.api_key:
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        url = f"{self.base_url.rstrip('/')}/geolocate/address"
        payload = {"lat": lat, "lon": lon, "count": 1}
        data = await self._post_json(url, payload)
        d = self._get_first_suggestion_data(data)
        if d is None:
            return None
        city = d.get("city") or d.get("settlement") or d.get("area")
        if not city or not isinstance(city, str) or not city.strip():
            return None
        region_name = (
            d.get("region") if isinstance(d.get("region"), str) else None
        )
        country_name = (
            d.get("country") if isinstance(d.get("country"), str) else None
        )
        return (city.strip(), region_name, country_name)
