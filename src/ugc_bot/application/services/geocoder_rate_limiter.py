"""Rate-limited GeocoderPort wrapper for Nominatim 1 req/sec policy."""

from typing import List, Optional, Tuple

from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.geocoder_rate_limit_store import (
    GeocoderRateLimitStore,
    InMemoryGeocoderRateLimitStore,
)


class RateLimitedGeocoder:
    """GeocoderPort wrapper that enforces a minimum delay between API requests.

    Used for Nominatim to comply with the 1 request per second usage policy.
    Uses a GeocoderRateLimitStore: in-memory (per process) or Redis (global
    across app instances). Sync methods (accepts_as_*) are passed through.
    """

    def __init__(
        self,
        delegate: GeocoderPort,
        delay_seconds: float,
        store: Optional[GeocoderRateLimitStore] = None,
    ) -> None:
        """Init: delegate, delay, optional store. Use Redis for global limit."""
        self._delegate = delegate
        self._store: GeocoderRateLimitStore = (
            store
            if store is not None
            else InMemoryGeocoderRateLimitStore(delay_seconds)
        )

    async def _with_rate_limit(self, coro):
        """Wait until allowed then run the delegate coroutine."""
        await self._store.wait_until_allowed()
        return await coro

    async def geocode(
        self,
        query: str,
        region: Optional[str] = None,
        country: str = "Russia",
    ) -> Optional[Tuple[float, float]]:
        """Rate-limited geocode; delegates to underlying geocoder."""
        return await self._with_rate_limit(
            self._delegate.geocode(query, region=region, country=country)
        )

    async def geocode_with_details(
        self,
        query: str,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Optional[Tuple[float, float, str, str, Optional[str], Optional[str]]]:
        """Rate-limited geocode_with_details."""
        return await self._with_rate_limit(
            self._delegate.geocode_with_details(
                query, region=region, country=country
            )
        )

    async def reverse_geocode(
        self, lat: float, lon: float
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Rate-limited reverse_geocode; delegates to underlying geocoder."""
        return await self._with_rate_limit(
            self._delegate.reverse_geocode(lat, lon)
        )

    async def get_multipolygon_wkt_for_queries(
        self,
        queries: List[Tuple[str, Optional[str], str]],
    ) -> Optional[str]:
        """Rate-limited get_multipolygon_wkt_for_queries."""
        return await self._with_rate_limit(
            self._delegate.get_multipolygon_wkt_for_queries(queries)
        )

    def accepts_as_populated_place(
        self, place_class: str, place_type: str
    ) -> bool:
        """Delegate to underlying geocoder (no rate limit for sync)."""
        return self._delegate.accepts_as_populated_place(
            place_class, place_type
        )

    def accepts_as_place_or_region(
        self, place_class: str, place_type: str
    ) -> bool:
        """Delegate to underlying geocoder (no rate limit for sync)."""
        return self._delegate.accepts_as_place_or_region(
            place_class, place_type
        )
