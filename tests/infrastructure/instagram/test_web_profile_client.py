"""Tests for Instagram Web Profile API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ugc_bot.infrastructure.instagram.web_profile_client import (
    WEB_PROFILE_URL,
    InstagramWebProfileClient,
)


def _make_session_mock(get_return_value):
    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=get_return_value)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    return mock_http


@pytest.mark.asyncio
async def test_get_profile_stats_by_username_returns_raw_dict() -> None:
    """Returns raw dict from web_profile_info (used in multi-provider chain)."""
    client = InstagramWebProfileClient()
    response_data = {
        "data": {"user": {"username": "x", "edge_followed_by": {"count": 1}}}
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data
    with patch(
        "ugc_bot.infrastructure.instagram.web_profile_client.AsyncSession"
    ) as mock_cls:
        mock_cls.return_value = _make_session_mock(mock_resp)

        result = await client.get_profile_stats_by_username("x")

    assert result == response_data


@pytest.mark.asyncio
async def test_get_profile_stats_with_provider_success() -> None:
    """Returns (data, 'instagram_web') on 200 with JSON."""
    client = InstagramWebProfileClient()
    response_data = {
        "data": {
            "user": {
                "username": "darbulat",
                "edge_followed_by": {"count": 100},
            },
        },
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data
    with patch(
        "ugc_bot.infrastructure.instagram.web_profile_client.AsyncSession"
    ) as mock_cls:
        mock_http = _make_session_mock(mock_resp)
        mock_cls.return_value = mock_http

        data, provider = await client.get_profile_stats_with_provider(
            "darbulat"
        )

    assert data == response_data
    assert provider == "instagram_web"
    call_args = mock_http.get.call_args
    assert call_args[0][0] == WEB_PROFILE_URL
    assert call_args[1]["params"] == {"username": "darbulat"}
    assert "User-Agent" in call_args[1]["headers"]
    assert call_args[1]["headers"]["X-IG-App-ID"] == "936619743392459"


@pytest.mark.asyncio
async def test_get_profile_stats_with_provider_empty_username() -> None:
    """Returns (None, 'instagram_web') for empty username."""
    client = InstagramWebProfileClient()
    data, provider = await client.get_profile_stats_with_provider("")
    assert data is None
    assert provider == "instagram_web"


@pytest.mark.asyncio
async def test_get_profile_stats_with_provider_http_error() -> None:
    """Returns (None, 'instagram_web') on non-2xx status (e.g. 404)."""
    client = InstagramWebProfileClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch(
        "ugc_bot.infrastructure.instagram.web_profile_client.AsyncSession"
    ) as mock_cls:
        mock_cls.return_value = _make_session_mock(mock_resp)

        data, provider = await client.get_profile_stats_with_provider("x")

    assert data is None
    assert provider == "instagram_web"


@pytest.mark.asyncio
async def test_get_profile_stats_with_provider_request_error() -> None:
    """Returns (None, 'instagram_web') on request/network error."""
    client = InstagramWebProfileClient()
    with patch(
        "ugc_bot.infrastructure.instagram.web_profile_client.AsyncSession"
    ) as mock_cls:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=OSError("network"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_http

        data, provider = await client.get_profile_stats_with_provider("x")

    assert data is None
    assert provider == "instagram_web"


@pytest.mark.asyncio
async def test_get_profile_stats_with_provider_non_dict_response() -> None:
    """Returns (None, 'instagram_web') when response is not a dict."""
    client = InstagramWebProfileClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    with patch(
        "ugc_bot.infrastructure.instagram.web_profile_client.AsyncSession"
    ) as mock_cls:
        mock_cls.return_value = _make_session_mock(mock_resp)

        data, provider = await client.get_profile_stats_with_provider("x")

    assert data is None
    assert provider == "instagram_web"
