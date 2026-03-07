"""Tests for geocoder factory wiring (provider selection and cache)."""

from ugc_bot.application.services.geocoder import NominatimGeocoder
from ugc_bot.application.services.geocoder_cache import CachingGeocoder
from ugc_bot.application.services.geocoder_dadata import DadataGeocoder
from ugc_bot.config import AppConfig
from ugc_bot.container.service_factory import build_geocoder


def _config_with_cache_disabled(**overrides: object) -> AppConfig:
    """Minimal config with cache disabled so we get bare geocoder."""
    base = {
        "BOT_TOKEN": "t",
        "DATABASE_URL": "db",
        "GEOCODER_CACHE_ENABLED": False,
    }
    return AppConfig.model_validate({**base, **overrides})


def test_build_geocoder_defaults_to_nominatim_when_cache_disabled() -> None:
    """With cache disabled, build_geocoder returns bare NominatimGeocoder."""
    config = _config_with_cache_disabled()
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, NominatimGeocoder)


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
