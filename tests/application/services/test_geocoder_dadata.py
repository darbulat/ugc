"""Tests for DadataGeocoder implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.geocoder_dadata import DadataGeocoder


def test_dadata_accepts_as_populated_place_and_region() -> None:
    """accepts_* methods encode Dadata taxonomy via (class, fias_level)."""
    geocoder = DadataGeocoder(api_key="token", enabled=True)
    assert geocoder.accepts_as_populated_place("fias", "4") is True
    assert geocoder.accepts_as_populated_place("fias", "6") is True
    assert geocoder.accepts_as_populated_place("fias", "1") is False

    assert geocoder.accepts_as_place_or_region("fias", "1") is True
    assert geocoder.accepts_as_place_or_region("fias", "4") is True
    assert geocoder.accepts_as_place_or_region("other", "4") is False


def test_dadata_headers_include_secret_when_set() -> None:
    """_headers adds X-Secret when secret is configured."""
    geocoder = DadataGeocoder(api_key="token", secret="secret", enabled=True)
    headers = geocoder._headers()
    assert headers["Authorization"] == "Token token"
    assert headers["X-Secret"] == "secret"


@pytest.mark.asyncio
async def test_dadata_geocode_with_details_disabled_returns_none() -> None:
    """geocode_with_details returns None when disabled."""
    geocoder = DadataGeocoder(api_key="token", enabled=False)
    assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_dadata_geocode_with_details_no_api_key_returns_none() -> None:
    """geocode_with_details returns None when api_key is missing."""
    geocoder = DadataGeocoder(api_key="", enabled=True)
    assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_dadata_geocode_with_details_success() -> None:
    """geocode_with_details parses coordinates and region/country."""
    geocoder = DadataGeocoder(
        api_key="token", enabled=True, base_url="https://dadata.test"
    )
    with patch(
        "ugc_bot.application.services.geocoder_dadata.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "suggestions": [
                {
                    "data": {
                        "geo_lat": "55.75",
                        "geo_lon": "37.62",
                        "fias_level": "4",
                        "region": "Москва",
                        "country": "Russia",
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode_with_details(
            "Moscow", region="Москва", country="Russia"
        )

    assert result == (55.75, 37.62, "fias", "4", "Москва", "Russia")


@pytest.mark.asyncio
async def test_dadata_geocode_delegates_to_geocode_with_details() -> None:
    """geocode returns (lat, lon) from geocode_with_details."""
    mock_details = AsyncMock(
        return_value=(55.75, 37.62, "fias", "4", None, None)
    )
    with patch.object(DadataGeocoder, "geocode_with_details", mock_details):
        geocoder = DadataGeocoder(api_key="token", enabled=True)
        assert await geocoder.geocode("Moscow") == (55.75, 37.62)
    mock_details.assert_awaited_once()


@pytest.mark.asyncio
async def test_dadata_geocode_with_details_json_not_dict_returns_none() -> None:
    """geocode_with_details returns None when response JSON is not a dict."""
    geocoder = DadataGeocoder(
        api_key="token", enabled=True, base_url="https://dadata.test"
    )
    with patch(
        "ugc_bot.application.services.geocoder_dadata.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_dadata_geocode_with_details_missing_coords_returns_none() -> (
    None
):
    """geocode_with_details returns None when geo_lat/geo_lon are missing."""
    geocoder = DadataGeocoder(
        api_key="token", enabled=True, base_url="https://dadata.test"
    )
    with patch(
        "ugc_bot.application.services.geocoder_dadata.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "suggestions": [{"data": {"fias_level": "4"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_dadata_reverse_geocode_success() -> None:
    """reverse_geocode returns city and region/country from geolocate."""
    geocoder = DadataGeocoder(
        api_key="token", enabled=True, base_url="https://dadata.test"
    )
    with patch(
        "ugc_bot.application.services.geocoder_dadata.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "suggestions": [
                {
                    "data": {
                        "city": "Moscow",
                        "region": "Москва",
                        "country": "Russia",
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.reverse_geocode(55.75, 37.62)

    assert result == ("Moscow", "Москва", "Russia")
