"""Tests for geocoder factory wiring (provider selection by config)."""

from ugc_bot.application.services.geocoder import NominatimGeocoder
from ugc_bot.application.services.geocoder_dadata import DadataGeocoder
from ugc_bot.config import AppConfig
from ugc_bot.container.service_factory import build_geocoder


def test_build_geocoder_defaults_to_nominatim() -> None:
    """When provider is not set, build_geocoder returns NominatimGeocoder."""
    config = AppConfig.model_validate({"BOT_TOKEN": "t", "DATABASE_URL": "db"})
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, NominatimGeocoder)


def test_build_geocoder_uses_dadata_provider() -> None:
    """When GEOCODER_PROVIDER=dadata, build_geocoder returns DadataGeocoder."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "db",
            "GEOCODER_PROVIDER": "dadata",
            "DADATA_API_KEY": "token",
        }
    )
    geocoder = build_geocoder(config)
    assert isinstance(geocoder, DadataGeocoder)
