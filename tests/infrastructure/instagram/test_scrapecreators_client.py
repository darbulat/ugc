"""Tests for ScrapeCreators Instagram profile client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ugc_bot.application.errors import ScrapeCreatorsAPIError
from ugc_bot.infrastructure.instagram.scrapecreators_client import (
    ScrapeCreatorsProfileClient,
)


@pytest.mark.asyncio
async def test_get_profile_not_configured() -> None:
    """Returns None when API key is empty (client not configured)."""
    client = ScrapeCreatorsProfileClient(api_key="")
    assert await client.get_profile("handle") is None


@pytest.mark.asyncio
async def test_get_profile_empty_handle() -> None:
    """Returns None for empty handle."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    assert await client.get_profile("") is None
    assert await client.get_profile("   ") is None


@pytest.mark.asyncio
async def test_get_profile_success() -> None:
    """Returns full response dict on 200 with success and data."""
    client = ScrapeCreatorsProfileClient(
        api_key="secret",
        base_url="https://api.scrapecreators.com",
    )
    response_data = {
        "success": True,
        "data": {"user": {"username": "jane", "id": "123"}},
        "status": "ok",
    }

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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

        result = await client.get_profile("jane")

    assert result == response_data
    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["headers"]["x-api-key"] == "secret"
    assert call_kwargs["params"]["handle"] == "jane"
    assert "trim" not in call_kwargs["params"]


@pytest.mark.asyncio
async def test_get_profile_with_trim_sends_param() -> None:
    """When trim=True, params include trim=true."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    response_data = {
        "success": True,
        "data": {"user": {}},
        "status": "ok",
    }

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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

        await client.get_profile("handle", trim=True)

    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["params"]["trim"] == "true"


@pytest.mark.asyncio
async def test_get_profile_http_error_raises_scrapecreators_api_error() -> None:
    """Raises ScrapeCreatorsAPIError on HTTP 4xx/5xx so scheduler can alert."""
    client = ScrapeCreatorsProfileClient(api_key="key")

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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

        with pytest.raises(ScrapeCreatorsAPIError) as exc_info:
            await client.get_profile("jane")

    assert exc_info.value.status_code == 404
    assert "404" in str(exc_info.value)
    assert exc_info.value.response_text == "Not Found"


@pytest.mark.asyncio
async def test_get_profile_5xx_retries_then_succeeds() -> None:
    """On 5xx, client retries with backoff; success on second attempt."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    response_data = {
        "success": True,
        "data": {"user": {"username": "jane"}},
        "status": "ok",
    }
    mock_500 = MagicMock()
    mock_500.status_code = 500
    mock_500.text = "Server Error"
    mock_500.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_500
        )
    )
    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = response_data
    mock_200.raise_for_status = MagicMock()

    with (
        patch(
            "ugc_bot.infrastructure.instagram.scrapecreators_client.asyncio.sleep",
            AsyncMock(),
        ),
        patch(
            "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
        ) as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_500, mock_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile("jane")

    assert result == response_data
    assert mock_client.get.await_count == 2


@pytest.mark.asyncio
async def test_get_profile_402_out_of_credits_raises() -> None:
    """Raises ScrapeCreatorsAPIError on 402 (out of credits) for alerting."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    response_body = (
        '{"success":false,"message":"Looks like you\'re out of credits :("}'
    )

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.text = response_body
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "402",
                request=MagicMock(),
                response=mock_resp,
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ScrapeCreatorsAPIError) as exc_info:
            await client.get_profile("dankebeerr")

    assert exc_info.value.status_code == 402
    assert exc_info.value.response_text == response_body


@pytest.mark.asyncio
async def test_get_profile_request_error_returns_none() -> None:
    """Returns None on RequestError (e.g. network)."""
    client = ScrapeCreatorsProfileClient(api_key="key")

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("network error")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_non_dict_response_returns_none() -> None:
    """Returns None when response JSON is not a dict."""
    client = ScrapeCreatorsProfileClient(api_key="key")

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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

        result = await client.get_profile("jane")

    assert result is None


@pytest.mark.asyncio
async def test_get_profile_missing_success_or_data_returns_none() -> None:
    """Returns None when success is False or data is missing."""
    client = ScrapeCreatorsProfileClient(api_key="key")

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": False, "data": {}}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await client.get_profile("jane")

    assert result is None

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
    ) as mock_client_cls:
        mock_response2 = MagicMock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {"success": True}
        mock_response2.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response2)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client
        result2 = await client.get_profile("jane")
    assert result2 is None


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_returns_profile() -> None:
    """get_profile_stats_by_username returns profile dict on success."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    response_data = {
        "success": True,
        "data": {"user": {"username": "jane"}},
        "status": "ok",
    }
    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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
async def test_get_profile_stats_with_provider_returns_tuple() -> None:
    """get_profile_stats_with_provider returns (data, 'scrapecreators')."""
    client = ScrapeCreatorsProfileClient(api_key="key")
    response_data = {
        "success": True,
        "data": {"user": {"username": "x"}},
        "status": "ok",
    }

    with patch(
        "ugc_bot.infrastructure.instagram.scrapecreators_client.httpx.AsyncClient"
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

        data, provider = await client.get_profile_stats_with_provider("x")

    assert data == response_data
    assert provider == "scrapecreators"
