"""Tests for geocoder service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.application.services.geocoder import (
    NominatimGeocoder,
    _extract_country_from_address,
    _extract_region_from_address,
    _geojson_geometry_to_wkt,
    wkt_multipoint_from_coords,
    wkt_multipoint_from_lat_lon,
    wkt_multipolygon_from_polygon_wkts,
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


def test_geojson_geometry_to_wkt_polygon() -> None:
    """_geojson_geometry_to_wkt converts Polygon to WKT."""
    geojson = {
        "type": "Polygon",
        "coordinates": [
            [
                [37.6, 55.75],
                [37.7, 55.75],
                [37.7, 55.76],
                [37.6, 55.76],
                [37.6, 55.75],
            ]
        ],
    }
    assert _geojson_geometry_to_wkt(geojson) == (
        "POLYGON((37.6 55.75, 37.7 55.75, 37.7 55.76, 37.6 55.76, 37.6 55.75))"
    )


def test_geojson_geometry_to_wkt_multipolygon() -> None:
    """_geojson_geometry_to_wkt converts MultiPolygon to WKT."""
    geojson = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [37.6, 55.75],
                    [37.7, 55.75],
                    [37.7, 55.76],
                    [37.6, 55.76],
                    [37.6, 55.75],
                ]
            ],
        ],
    }
    expected = (
        "MULTIPOLYGON(((37.6 55.75, 37.7 55.75, 37.7 55.76, "
        "37.6 55.76, 37.6 55.75)))"
    )
    assert _geojson_geometry_to_wkt(geojson) == expected


def test_geojson_geometry_to_wkt_point_returns_none() -> None:
    """_geojson_geometry_to_wkt returns None for Point (not supported)."""
    geom = {"type": "Point", "coordinates": [37.6, 55.75]}
    assert _geojson_geometry_to_wkt(geom) is None


def test_geojson_geometry_to_wkt_invalid_returns_none() -> None:
    """_geojson_geometry_to_wkt returns None for invalid input."""
    assert _geojson_geometry_to_wkt(None) is None
    assert _geojson_geometry_to_wkt({}) is None
    assert (
        _geojson_geometry_to_wkt({"type": "Polygon", "coordinates": []}) is None
    )
    assert (
        _geojson_geometry_to_wkt({"type": "Polygon", "coordinates": [[]]})
        is None
    )


def test_geojson_geometry_to_wkt_multipolygon_skips_empty_poly() -> None:
    """MultiPolygon skips empty poly and returns WKT from valid one."""
    geojson = {
        "type": "MultiPolygon",
        "coordinates": [
            [],  # empty poly -> continue
            [
                [
                    [37.6, 55.75],
                    [37.7, 55.75],
                    [37.7, 55.76],
                    [37.6, 55.76],
                    [37.6, 55.75],
                ]
            ],
        ],
    }
    result = _geojson_geometry_to_wkt(geojson)
    assert result is not None
    assert "37.6 55.75" in result


def test_geojson_geometry_to_wkt_multipolygon_all_empty_returns_none() -> None:
    """MultiPolygon with all empty or invalid polys returns None."""
    assert (
        _geojson_geometry_to_wkt(
            {"type": "MultiPolygon", "coordinates": [[], [[]]]}
        )
        is None
    )


def test_wkt_multipolygon_from_polygon_wkts_empty() -> None:
    """wkt_multipolygon_from_polygon_wkts returns None for empty list."""
    assert wkt_multipolygon_from_polygon_wkts([]) is None


def test_wkt_multipolygon_from_polygon_wkts_single_polygon() -> None:
    """wkt_multipolygon_from_polygon_wkts: one POLYGON -> MULTIPOLYGON."""
    wkt = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
    assert wkt_multipolygon_from_polygon_wkts([wkt]) == (
        "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))"
    )


def test_wkt_multipolygon_from_polygon_wkts_multiple() -> None:
    """wkt_multipolygon_from_polygon_wkts merges several POLYGONs."""
    a = "POLYGON((0 0, 1 0, 1 1, 0 0))"
    b = "POLYGON((2 2, 3 2, 3 3, 2 2))"
    result = wkt_multipolygon_from_polygon_wkts([a, b])
    assert result is not None
    assert "((0 0, 1 0, 1 1, 0 0))" in result
    assert "((2 2, 3 2, 3 3, 2 2))" in result


def test_wkt_multipolygon_from_polygon_wkts_multipolygon_input() -> None:
    """wkt_multipolygon_from_polygon_wkts accepts MULTIPOLYGON WKT input."""
    wkt = "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))"
    result = wkt_multipolygon_from_polygon_wkts([wkt])
    assert result is not None
    assert "((0 0, 1 0, 1 1, 0 0))" in result


def test_wkt_multipolygon_from_polygon_wkts_all_invalid_returns_none() -> None:
    """wkt_multipolygon_from_polygon_wkts returns None when no valid WKT."""
    result = wkt_multipolygon_from_polygon_wkts(["INVALID", "  ", "POINT(0 0)"])
    assert result is None


def test_extract_region_from_address() -> None:
    """Extract region: state, then state_district, then county."""
    assert _extract_region_from_address(None) is None
    assert _extract_region_from_address("not a dict") is None
    assert _extract_region_from_address({}) is None
    assert _extract_region_from_address({"state": "Tatarstan"}) == "Tatarstan"
    assert (
        _extract_region_from_address({"state_district": "Greater London"})
        == "Greater London"
    )
    assert (
        _extract_region_from_address(
            {"state": "England", "state_district": "Greater London"}
        )
        == "England"
    )
    assert (
        _extract_region_from_address({"county": "Some County"}) == "Some County"
    )


def test_extract_country_from_address() -> None:
    """_extract_country_from_address returns address.country or None."""
    assert _extract_country_from_address(None) is None
    assert _extract_country_from_address({}) is None
    assert _extract_country_from_address({"country": "Russia"}) == "Russia"
    assert (
        _extract_country_from_address(
            {"country": "United Kingdom", "state": "England"}
        )
        == "United Kingdom"
    )


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


@pytest.mark.asyncio
async def test_nominatim_geocoder_geocode_with_details_success() -> None:
    """geocode_with_details returns (lat, lon, class, type) from Nominatim."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.7558",
                "lon": "37.6173",
                "class": "place",
                "type": "city",
                "display_name": "Moscow",
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode_with_details("Moscow")
        assert result == (55.7558, 37.6173, "place", "city", None, None)


@pytest.mark.asyncio
async def test_geocode_with_details_with_region() -> None:
    """Query with region appends region and country to request."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "52.52",
                "lon": "13.405",
                "class": "place",
                "type": "city",
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        await geocoder.geocode_with_details(
            "City", region="Region", country="Russia"
        )
        call_kw = mock_client.get.call_args[1]
        assert "Region, Russia" in call_kw["params"]["q"]


@pytest.mark.asyncio
async def test_geocode_with_details_no_country_when_country_empty() -> None:
    """When country is None or empty, query has no country (no default)."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "51.51", "lon": "-0.13", "class": "place", "type": "city"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        await geocoder.geocode_with_details("London", country=None)
        call_kw = mock_client.get.call_args[1]
        assert call_kw["params"]["q"] == "London"


@pytest.mark.asyncio
async def test_geocode_with_details_returns_region_from_address() -> None:
    """When response has address.state, 5th element is region from Nominatim."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.79",
                "lon": "49.12",
                "class": "place",
                "type": "city",
                "address": {"state": "Tatarstan", "country": "Russia"},
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode_with_details("Kazan")
        assert result is not None
        assert result[:4] == (55.79, 49.12, "place", "city")
        assert result[4] == "Tatarstan"
        assert result[5] == "Russia"


@pytest.mark.asyncio
async def test_nominatim_geocoder_geocode_with_details_missing_class_type() -> (
    None
):
    """geocode_with_details uses empty string when class/type missing."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "55.75", "lon": "37.6", "display_name": "Moscow"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode_with_details("Moscow")
        assert result == (55.75, 37.6, "", "", None, None)


@pytest.mark.asyncio
async def test_nominatim_geocoder_geocode_with_details_uses_category() -> None:
    """geocode_with_details uses 'category' when 'class' missing (jsonv2)."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.75",
                "lon": "37.6",
                "category": "place",
                "type": "city",
            }
        ]  # no "class", only "category"
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.geocode_with_details("Moscow")
        assert result == (55.75, 37.6, "place", "city", None, None)


@pytest.mark.asyncio
async def test_geocode_with_details_disabled_returns_none() -> None:
    """When disabled, geocode_with_details returns None."""
    geocoder = NominatimGeocoder(enabled=False)
    assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_geocode_with_details_http_error_returns_none() -> None:
    """On HTTP error geocode_with_details returns None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.geocode_with_details("Moscow") is None


@pytest.mark.asyncio
async def test_geocode_with_details_invalid_coords_returns_none() -> None:
    """Out-of-range lat/lon returns None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "99", "lon": "200", "class": "place", "type": "city"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode_with_details("Bad") is None


@pytest.mark.asyncio
async def test_geocode_with_details_empty_response_returns_none() -> None:
    """Empty JSON list returns None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.geocode_with_details("X") is None


@pytest.mark.asyncio
async def test_geocode_with_details_first_not_dict_returns_none() -> None:
    """When first result is not a dict, return None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.geocode_with_details("Y") is None


@pytest.mark.asyncio
async def test_geocode_with_details_missing_lat_lon_returns_none() -> None:
    """When lat or lon missing in response, return None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.geocode_with_details("Z") is None


@pytest.mark.asyncio
async def test_geocode_with_details_invalid_lat_lon_returns_none() -> None:
    """When lat/lon not convertible to float, return None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "not_a_number",
                "lon": "37.6",
                "class": "place",
                "type": "city",
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.geocode_with_details("W") is None


@pytest.mark.asyncio
async def test_search_osm_id_success() -> None:
    """_search_osm_id returns (type_letter, osm_id) from search response."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.75",
                "lon": "37.6",
                "osm_type": "relation",
                "osm_id": 123,
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder._search_osm_id("Moscow")
        assert result == ("R", 123)


@pytest.mark.asyncio
async def test_search_osm_id_with_region_appends_to_query() -> None:
    """_search_osm_id with region includes region in search query."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.79",
                "lon": "49.12",
                "osm_type": "relation",
                "osm_id": 123,
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder._search_osm_id(
            "Kazan", region="Tatarstan", country="Russia"
        )
        assert result == ("R", 123)
        call_args = mock_client.get.call_args
        assert "Kazan, Tatarstan, Russia" in call_args[1]["params"]["q"]


@pytest.mark.asyncio
async def test_search_osm_id_empty_osm_type_defaults_to_r() -> None:
    """_search_osm_id uses 'R' when osm_type is missing or empty."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "55.75", "lon": "37.6", "osm_id": 456}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder._search_osm_id("Moscow")
        assert result == ("R", 456)


@pytest.mark.asyncio
async def test_search_osm_id_invalid_osm_type_defaults_to_r() -> None:
    """_search_osm_id uses 'R' when osm_type letter is not N, W, or R."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.75",
                "lon": "37.6",
                "osm_type": "unknown",
                "osm_id": 789,
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder._search_osm_id("Moscow")
        assert result == ("R", 789)


@pytest.mark.asyncio
async def test_search_osm_id_returns_none_when_disabled() -> None:
    """_search_osm_id returns None when geocoder disabled."""
    geocoder = NominatimGeocoder(enabled=False)
    assert await geocoder._search_osm_id("Moscow") is None


@pytest.mark.asyncio
async def test_search_osm_id_http_error_returns_none() -> None:
    """_search_osm_id returns None on request exception."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder._search_osm_id("Moscow") is None


@pytest.mark.asyncio
async def test_search_osm_id_osm_id_none_returns_none() -> None:
    """_search_osm_id returns None when osm_id is missing."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"lat": "55.75", "lon": "37.6", "osm_type": "relation"}
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder._search_osm_id("Moscow") is None


@pytest.mark.asyncio
async def test_search_osm_id_invalid_osm_id_returns_none() -> None:
    """_search_osm_id returns None when osm_id is not int-convertible."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "lat": "55.75",
                "lon": "37.6",
                "osm_type": "relation",
                "osm_id": "not_an_int",
            }
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder._search_osm_id("Moscow") is None


@pytest.mark.asyncio
async def test_search_osm_id_first_element_not_dict_returns_none() -> None:
    """_search_osm_id returns None when first result is not a dict."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = ["not_a_dict"]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder._search_osm_id("Moscow") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_success() -> None:
    """get_polygon_wkt returns WKT when search and lookup succeed."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                return MagicMock(
                    json=lambda: {
                        "features": [
                            {
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [
                                        [
                                            [37.6, 55.75],
                                            [37.7, 55.75],
                                            [37.7, 55.76],
                                            [37.6, 55.76],
                                            [37.6, 55.75],
                                        ]
                                    ],
                                }
                            }
                        ]
                    },
                    raise_for_status=MagicMock(),
                )
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 123}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        result = await geocoder.get_polygon_wkt("Moscow")
        assert result is not None
        assert "37.6 55.75" in result
        assert "POLYGON" in result


@pytest.mark.asyncio
async def test_get_polygon_wkt_search_returns_none() -> None:
    """get_polygon_wkt returns None when search returns no osm_id."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.get_polygon_wkt("Unknown") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_lookup_raises_returns_none() -> None:
    """get_polygon_wkt returns None when lookup request raises."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    search_resp = MagicMock(
        json=lambda: [{"osm_type": "relation", "osm_id": 1}],
        raise_for_status=MagicMock(),
    )
    lookup_resp = MagicMock(
        json=lambda: {},
        raise_for_status=MagicMock(side_effect=Exception("HTTP 500")),
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=[search_resp, lookup_resp])
        client_cls.return_value = mock_client

        assert await geocoder.get_polygon_wkt("Moscow") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_lookup_not_dict_returns_none() -> None:
    """get_polygon_wkt returns None when lookup returns non-dict (e.g. list)."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                resp = MagicMock(raise_for_status=MagicMock())
                resp.json = lambda: []  # not a dict
                return resp
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 1}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        assert await geocoder.get_polygon_wkt("Moscow") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_no_features_returns_none() -> None:
    """get_polygon_wkt returns None when features missing or empty."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                return MagicMock(
                    json=lambda: {"features": []},
                    raise_for_status=MagicMock(),
                )
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 1}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        assert await geocoder.get_polygon_wkt("Moscow") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_first_feature_not_dict_returns_none() -> None:
    """get_polygon_wkt returns None when first feature is not a dict."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                return MagicMock(
                    json=lambda: {"features": ["not a dict"]},
                    raise_for_status=MagicMock(),
                )
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 1}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        assert await geocoder.get_polygon_wkt("Moscow") is None


@pytest.mark.asyncio
async def test_get_polygon_wkt_geometry_not_dict_returns_none() -> None:
    """get_polygon_wkt returns None when geometry is not a dict."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                return MagicMock(
                    json=lambda: {"features": [{"geometry": [37.6, 55.75]}]},
                    raise_for_status=MagicMock(),
                )
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 1}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        assert await geocoder.get_polygon_wkt("Moscow") is None


@pytest.mark.asyncio
async def test_get_multipolygon_wkt_for_queries_empty_returns_none() -> None:
    """get_multipolygon_wkt_for_queries returns None for empty queries."""
    geocoder = NominatimGeocoder(enabled=True)
    assert await geocoder.get_multipolygon_wkt_for_queries([]) is None


@pytest.mark.asyncio
async def test_get_multipolygon_wkt_for_queries_skips_empty_query() -> None:
    """get_multipolygon_wkt_for_queries skips empty query strings."""
    geocoder = NominatimGeocoder(enabled=True)
    result = await geocoder.get_multipolygon_wkt_for_queries(
        [("", None, "Russia"), ("  ", None, "Russia")]
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_multipolygon_wkt_for_queries_combines_polygons() -> None:
    """get_multipolygon_wkt_for_queries returns combined WKT for two queries."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    call_count = 0

    def get_side_effect(*args, **kwargs):
        nonlocal call_count
        params = kwargs.get("params", {})
        if "osm_ids" in params:
            call_count += 1
            coords = (
                [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
                if call_count == 1
                else [[[2, 2], [3, 2], [3, 3], [2, 2]]]
            )
            return MagicMock(
                json=lambda: {
                    "features": [
                        {"geometry": {"type": "Polygon", "coordinates": coords}}
                    ]
                },
                raise_for_status=MagicMock(),
            )
        return MagicMock(
            json=lambda: [{"osm_type": "relation", "osm_id": call_count}],
            raise_for_status=MagicMock(),
        )

    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        result = await geocoder.get_multipolygon_wkt_for_queries(
            [("City1", None, "Russia"), ("City2", None, "Russia")]
        )
        assert result is not None
        assert "MULTIPOLYGON" in result
        assert "0 0" in result
        assert "2 2" in result


@pytest.mark.asyncio
async def test_get_multipolygon_wkt_for_queries_country_none_uses_russia() -> (
    None
):
    """get_multipolygon_wkt_for_queries uses 'Russia' when country is None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        def get_side_effect(*args, **kwargs):
            params = kwargs.get("params", {})
            if "osm_ids" in params:
                return MagicMock(
                    json=lambda: {
                        "features": [
                            {
                                "geometry": {
                                    "type": "Polygon",
                                    "coordinates": [
                                        [
                                            [37.6, 55.75],
                                            [37.7, 55.75],
                                            [37.7, 55.76],
                                            [37.6, 55.76],
                                            [37.6, 55.75],
                                        ]
                                    ],
                                }
                            }
                        ]
                    },
                    raise_for_status=MagicMock(),
                )
            return MagicMock(
                json=lambda: [{"osm_type": "relation", "osm_id": 1}],
                raise_for_status=MagicMock(),
            )

        mock_client.get = AsyncMock(side_effect=get_side_effect)
        client_cls.return_value = mock_client

        result = await geocoder.get_multipolygon_wkt_for_queries(
            [("Moscow", None, "")]
        )
        assert result is not None
        assert "37.6 55.75" in result


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_disabled_returns_none() -> None:
    """When disabled, reverse_geocode returns None."""
    geocoder = NominatimGeocoder(enabled=False)
    assert await geocoder.reverse_geocode(55.75, 37.6) is None


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_out_of_range_returns_none() -> None:
    """Out-of-range lat/lon returns None."""
    geocoder = NominatimGeocoder(enabled=True)
    assert await geocoder.reverse_geocode(100, 0) is None
    assert await geocoder.reverse_geocode(0, 200) is None


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_success() -> None:
    """reverse_geocode returns (city, region, country) from Nominatim."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "lat": "55.7558",
            "lon": "37.6173",
            "address": {
                "city": "Moscow",
                "state": "Moscow",
                "country": "Russia",
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.reverse_geocode(55.7558, 37.6173)
        assert result == ("Moscow", "Moscow", "Russia")


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_prefers_town_over_county() -> None:
    """reverse_geocode prefers city, town, village, then county."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "address": {
                "town": "Small Town",
                "state": "State",
                "country": "RU",
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.reverse_geocode(55.0, 37.0)
        assert result == ("Small Town", "State", "RU")


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_no_city_in_address_returns_none() -> (
    None
):
    """When address has no city/town/village, return None."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "address": {"road": "Highway", "country": "Russia"},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.reverse_geocode(55.0, 37.0) is None


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_http_error_returns_none() -> None:
    """reverse_geocode returns None on HTTP/connection error."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.reverse_geocode(55.75, 37.62) is None


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_city_from_county_only() -> None:
    """reverse_geocode uses county when city/town/village are missing."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "address": {
                "county": "Some County",
                "state": "State Name",
                "country": "Russia",
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.reverse_geocode(55.75, 37.62)
        assert result is not None
        assert result[0] == "Some County"


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_city_as_dict_extracts_name() -> None:
    """reverse_geocode gets city from dict with 'name' when API returns it."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "address": {
                "city": {"name": "Moscow", "place_id": 123},
                "country": "Russia",
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        result = await geocoder.reverse_geocode(55.75, 37.62)
        assert result is not None
        assert result[0] == "Moscow"


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_response_not_dict_returns_none() -> (
    None
):
    """reverse_geocode returns None when API response is not a dict."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
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

        assert await geocoder.reverse_geocode(55.75, 37.62) is None


@pytest.mark.asyncio
async def test_nominatim_reverse_geocode_address_not_dict_returns_none() -> (
    None
):
    """reverse_geocode returns None when address is not a dict."""
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        enabled=True,
    )
    with patch(
        "ugc_bot.application.services.geocoder.httpx.AsyncClient"
    ) as client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"address": "not_a_dict"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client

        assert await geocoder.reverse_geocode(55.75, 37.62) is None
