"""Tests for geocoder service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.geocoder import (
    NominatimGeocoder,
    wkt_multipoint_from_coords,
    wkt_multipoint_from_lat_lon,
    wkt_point_from_lat_lon,
)


def test_wkt_multipoint_from_lat_lon() -> None:
    """WKT MULTIPOINT uses lon, lat order (SRID 4326)."""
    assert (
        wkt_multipoint_from_lat_lon(55.75, 37.6) == "MULTIPOINT((37.6 55.75))"
    )
    assert wkt_multipoint_from_lat_lon(0.0, 0.0) == "MULTIPOINT((0.0 0.0))"


def test_wkt_multipoint_from_coords() -> None:
    """WKT MULTIPOINT from list of (lat, lon), deduplicated points."""
    assert wkt_multipoint_from_coords([]) == ""
    assert (
        wkt_multipoint_from_coords([(55.75, 37.6)])
        == "MULTIPOINT((37.6 55.75))"
    )
    assert (
        wkt_multipoint_from_coords([(55.75, 37.6), (55.83, 49.06)])
        == "MULTIPOINT((37.6 55.75),(49.06 55.83))"
    )


def test_wkt_point_from_lat_lon() -> None:
    """WKT POINT uses lon, lat order."""
    assert wkt_point_from_lat_lon(55.75, 37.6) == "POINT(37.6 55.75)"


@pytest.mark.asyncio
async def test_nominatim_geocoder_disabled_returns_none() -> None:
    """When disabled, geocode returns None."""
    geocoder = NominatimGeocoder(enabled=False)
    assert await geocoder.geocode("Moscow") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_empty_query_returns_none() -> None:
    """Empty query returns None."""
    geocoder = NominatimGeocoder(enabled=True)
    assert await geocoder.geocode("") is None
    assert await geocoder.geocode("   ") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_success() -> None:
    """Successful response returns (lat, lon)."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "55.7558", "lon": "37.6173", "display_name": "Moscow"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode("Moscow")
        assert result == (55.7558, 37.6173)


@pytest.mark.asyncio
async def test_nominatim_geocoder_with_region() -> None:
    """Query with region appends region and Russia to query."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "52.52", "lon": "13.405", "display_name": "Berlin"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        await geocoder.geocode("City", region="Region")
        call_kw = mock_client.get.call_args[1]
        assert "Region, Russia" in call_kw["params"]["q"]


@pytest.mark.asyncio
async def test_nominatim_geocoder_empty_response_returns_none() -> None:
    """Empty JSON list returns None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("UnknownCity") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_http_error_returns_none() -> None:
    """HTTP error returns None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=Exception("HTTP 503")
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("Moscow") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_invalid_coords_returns_none() -> None:
    """Out-of-range lat/lon in response returns None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "99", "lon": "37.6", "display_name": "Bad"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("Bad") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_non_dict_first_element_returns_none() -> None:
    """When first result is not a dict, return None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["not a dict"]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("X") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_missing_lat_lon_returns_none() -> None:
    """When lat or lon missing in response, return None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"display_name": "No coords"}]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("Y") is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_invalid_lat_lon_type_returns_none() -> None:
    """When lat/lon are not convertible to float, return None."""
    geocoder = NominatimGeocoder(enabled=True)
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"lat": "not_a_number", "lon": "37.6"}]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode("Z") is None
