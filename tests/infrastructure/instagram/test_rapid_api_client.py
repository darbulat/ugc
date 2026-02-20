"""Tests for Rapid API Instagram client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.instagram.rapid_api_client import (
    HttpInstagramRapidApiClient,
)


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_not_configured() -> None:
    """Returns None when API key or host is empty."""
    client = HttpInstagramRapidApiClient(api_key="", host="")
    assert await client.get_profile_stats_by_username("any") is None

    client = HttpInstagramRapidApiClient(api_key="key", host="")
    assert await client.get_profile_stats_by_username("any") is None

    client = HttpInstagramRapidApiClient(api_key="", host="host")
    assert await client.get_profile_stats_by_username("any") is None


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_empty_username() -> None:
    """Returns None for empty username."""
    client = HttpInstagramRapidApiClient(api_key="key", host="host")
    assert await client.get_profile_stats_by_username("") is None
    assert await client.get_profile_stats_by_username("   ") is None


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_success() -> None:
    """Returns parsed JSON on 200 response."""
    client = HttpInstagramRapidApiClient(
        api_key="key",
        host="instagram-v2",
        path="/user/details-by-username",
    )
    response_data = {
        "data": {"username": "jane", "counts": {"followed_by": 100}}
    }

    with patch(
        "ugc_bot.infrastructure.instagram.rapid_api_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile_stats_by_username("jane")

    assert result == response_data


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_http_error_returns_none() -> None:
    """Returns None on HTTP error."""
    import httpx

    client = HttpInstagramRapidApiClient(api_key="key", host="host")

    with patch(
        "ugc_bot.infrastructure.instagram.rapid_api_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "err",
                request=MagicMock(),
                response=mock_resp,
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile_stats_by_username("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_request_error_returns_none() -> (
    None
):
    """Returns None on RequestError (e.g. network)."""
    import httpx

    client = HttpInstagramRapidApiClient(api_key="key", host="host")

    with patch(
        "ugc_bot.infrastructure.instagram.rapid_api_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("network error")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile_stats_by_username("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_non_dict_response() -> None:
    """Returns None when response is not a dict."""
    client = HttpInstagramRapidApiClient(api_key="key", host="host")

    with patch(
        "ugc_bot.infrastructure.instagram.rapid_api_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [1, 2, 3]
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile_stats_by_username("jane")

    assert result is None


@pytest.mark.asyncio
async def test_param_style_url_sends_full_profile_url() -> None:
    """param_style=url sends query param url with full Instagram profile URL."""
    client = HttpInstagramRapidApiClient(
        api_key="key",
        host="instagram-statistics-api.p.rapidapi.com",
        path="/community",
        param_style="url",
    )
    response_data = {"data": {"username": "therock"}}

    with patch(
        "ugc_bot.infrastructure.instagram.rapid_api_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile_stats_by_username("therock")

    assert result == response_data
    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["params"] == {
        "url": "https://www.instagram.com/therock/"
    }
    assert (
        "instagram-statistics-api.p.rapidapi.com"
        in mock_client.get.call_args[0][0]
    )
