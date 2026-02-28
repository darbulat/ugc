"""Geocoding service: resolve city/address to coordinates (lat, lon)."""

from typing import Optional, Tuple

import httpx


def wkt_multipoint_from_lat_lon(lat: float, lon: float) -> str:
    """Build WKT MULTIPOINT for one point (SRID 4326: lon, lat order)."""
    return f"MULTIPOINT(({lon} {lat}))"


def wkt_point_from_lat_lon(lat: float, lon: float) -> str:
    """Build WKT POINT (SRID 4326: lon, lat order)."""
    return f"POINT({lon} {lat})"


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

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
    ) -> Optional[Tuple[float, float]]:
        """Return (latitude, longitude) for the query, or None if not found."""
        if not self._enabled or not (query or "").strip():
            return None
        q = query.strip()
        if region and region.strip():
            q = f"{q}, {region.strip()}, Russia"
        else:
            q = f"{q}, Russia"
        url = f"{self._base_url}/search"
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
