"""Tests for geocoder factory wiring (provider selection and cache)."""

from ugc_bot.application.services.geocoder import NominatimGeocoder
from ugc_bot.application.services.geocoder_cache import CachingGeocoder
from ugc_bot.application.services.geocoder_dadata import DadataGeocoder
from ugc_bot.application.services.geocoder_rate_limit_store import (
    RedisGeocoderRateLimitStore,
)
from ugc_bot.application.services.geocoder_rate_limiter import (
    RateLimitedGeocoder,
)
from ugc_bot.config import AppConfig
from ugc_bot.container.service_factory import build_geocoder
from ugc_bot.infrastructure.geocoder_cache_memory import GeocoderCacheMemory


def _config_with_cache_disabled(**overrides: object) -> AppConfig:
    """Minimal config with cache disabled so we get bare geocoder."""
    base = {
        "BOT_TOKEN": "t",
        "DATABASE_URL": "db",
        "GEOCODER_CACHE_ENABLED": False,
    }
    return AppConfig.model_validate({**base, **overrides})


def test_build_geocoder_nominatim_cache_disabled_returns_rate_limited() -> None:
    """With cache disabled, build_geocoder returns RateLimited(Nominatim)."""
    config = _config_with_cache_disabled()
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, RateLimitedGeocoder)
    assert isinstance(geocoder._delegate, NominatimGeocoder)


def test_build_geocoder_nominatim_with_redis_url_uses_redis_store() -> None:
    """With cache disabled and REDIS_URL set, rate limit store is Redis."""
    config = _config_with_cache_disabled(REDIS_URL="redis://localhost:6379/1")
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, RateLimitedGeocoder)
    assert isinstance(geocoder._store, RedisGeocoderRateLimitStore)


def test_build_geocoder_uses_dadata_provider_when_cache_disabled() -> None:
    """Cache disabled + GEOCODER_PROVIDER=dadata -> DadataGeocoder."""
    config = _config_with_cache_disabled(
        GEOCODER_PROVIDER="dadata",
        DADATA_API_KEY="token",
    )
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, DadataGeocoder)


def test_build_geocoder_returns_caching_wrapper_when_cache_enabled() -> None:
    """With cache enabled (default), build_geocoder returns CachingGeocoder."""
    config = AppConfig.model_validate({"BOT_TOKEN": "t", "DATABASE_URL": "db"})
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, CachingGeocoder)


def test_build_geocoder_uses_memory_cache_when_backend_memory() -> None:
    """With cache enabled and cache_backend=memory, uses GeocoderCacheMemory."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "db",
            "GEOCODER_CACHE_ENABLED": True,
            "GEOCODER_CACHE_BACKEND": "memory",
        }
    )
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, CachingGeocoder)
    assert isinstance(geocoder._cache, GeocoderCacheMemory)
