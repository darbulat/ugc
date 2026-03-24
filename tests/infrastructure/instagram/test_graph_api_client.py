"""Tests for Instagram Graph API client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ugc_bot.application.errors import InstagramUserNotFoundError
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.infrastructure.instagram.graph_api_client import (
    HttpInstagramGraphApiClient,
    _parse_profile_response,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInstagramGraphApiClient,
)


@pytest.mark.asyncio
async def test_get_username_by_id_success() -> None:
    """Test successful username retrieval."""
    client = HttpInstagramGraphApiClient(access_token="test_token")

    mock_response = MagicMock()
    mock_response.json.return_value = {"username": "test_user"}
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username == "test_user"
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "123456" in call_args[0][0]
        assert call_args[1]["params"]["fields"] == "username"
        assert call_args[1]["params"]["access_token"] == "test_token"


@pytest.mark.asyncio
async def test_get_username_by_id_no_token() -> None:
    """Test username retrieval without access token."""
    client = HttpInstagramGraphApiClient(access_token="")

    username = await client.get_username_by_id("123456")

    assert username is None


@pytest.mark.asyncio
async def test_get_username_by_id_http_error() -> None:
    """Test username retrieval with HTTP error (no retry for 4xx)."""
    client = HttpInstagramGraphApiClient(
        access_token="test_token", retry_attempts=1
    )

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(), response=mock_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username is None
        mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_username_by_id_request_error() -> None:
    """Test username retrieval with request error (no retry when attempts=1)."""
    client = HttpInstagramGraphApiClient(
        access_token="test_token", retry_attempts=1
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.RequestError("Connection error")
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username is None
        mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_username_by_id_retry_succeeds_after_request_error() -> None:
    """Test retry: first call RequestError, second call returns username."""
    client = HttpInstagramGraphApiClient(
        access_token="test_token",
        retry_attempts=3,
        retry_delay_seconds=0.0,
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"username": "retry_user"}
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [
            httpx.RequestError("Connection error"),
            mock_response,
        ]
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username == "retry_user"
        assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_username_by_id_retry_succeeds_after_503() -> None:
    """Test retry: first call 503, second call returns username."""
    client = HttpInstagramGraphApiClient(
        access_token="test_token",
        retry_attempts=3,
        retry_delay_seconds=0.0,
    )

    error_response = MagicMock()
    error_response.status_code = 503
    error_response.text = "Service Unavailable"
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Service Unavailable",
        request=MagicMock(),
        response=error_response,
    )
    success_response = MagicMock()
    success_response.json.return_value = {"username": "after_503"}
    success_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [error_response, success_response]
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username == "after_503"
        assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_username_by_id_no_username_in_response() -> None:
    """Test username retrieval when response doesn't contain username."""
    client = HttpInstagramGraphApiClient(access_token="test_token")

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "123456"}
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username is None


@pytest.mark.asyncio
async def test_in_memory_client() -> None:
    """Test in-memory Instagram Graph API client."""
    client = InMemoryInstagramGraphApiClient(
        username_map={"123456": "test_user", "789012": "another_user"}
    )

    username1 = await client.get_username_by_id("123456")
    assert username1 == "test_user"

    username2 = await client.get_username_by_id("789012")
    assert username2 == "another_user"

    username3 = await client.get_username_by_id("unknown")
    assert username3 is None


def test_parse_profile_response_returns_none_when_no_username() -> None:
    """_parse_profile_response returns None when username missing."""
    assert _parse_profile_response({}) is None
    assert _parse_profile_response({"id": "123"}) is None


def test_parse_profile_response_returns_info() -> None:
    """_parse_profile_response returns InstagramProfileInfo with all fields."""
    data = {
        "username": "jane",
        "followers_count": 1000,
        "media_count": 42,
        "follows_count": 200,
        "biography": "Hello",
        "has_profile_pic": True,
    }
    info = _parse_profile_response(data)
    assert info is not None
    assert info.username == "jane"
    assert info.followers_count == 1000
    assert info.media_count == 42
    assert info.follows_count == 200
    assert info.biography == "Hello"
    assert info.has_profile_pic is True


def test_parse_profile_response_minimal_username_only() -> None:
    """_parse_profile_response works with only username."""
    info = _parse_profile_response({"username": "minimal"})
    assert info is not None
    assert info.username == "minimal"
    assert info.followers_count is None
    assert info.media_count is None


def test_parse_profile_response_invalid_int_returns_none_for_that_field() -> (
    None
):
    """_parse_profile_response treats invalid int as None for that field."""
    data = {
        "username": "x",
        "followers_count": "not_a_number",
        "media_count": 10,
    }
    info = _parse_profile_response(data)
    assert info is not None
    assert info.followers_count is None
    assert info.media_count == 10


def test_parse_profile_response_follower_count_and_profile_pic_format() -> None:
    """_parse_profile_response accepts follower_count and profile_pic."""
    data = {
        "name": "Звездный Таролог 🔮| Москва",
        "username": "m.black_pearl",
        "profile_pic": "https://scontent-ams4-1.cdninstagram.com/...",
        "is_verified_user": False,
        "follower_count": 1411,
        "id": "922288326999437",
    }
    info = _parse_profile_response(data)
    assert info is not None
    assert info.username == "m.black_pearl"
    assert info.followers_count == 1411
    assert info.has_profile_pic is True
    assert info.media_count is None
    assert info.follows_count is None
    assert info.biography is None


@pytest.mark.asyncio
async def test_get_profile_by_id_success() -> None:
    """get_profile_by_id returns InstagramProfileInfo on success."""
    client = HttpInstagramGraphApiClient(access_token="test_token")
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "username": "jane",
        "followers_count": 500,
        "media_count": 10,
    }
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        info = await client.get_profile_by_id("123456")

        assert info is not None
        assert info.username == "jane"
        assert info.followers_count == 500
        assert info.media_count == 10
        call_args = mock_client.get.call_args
        assert "follower_count" in call_args[1]["params"]["fields"]
        assert "username" in call_args[1]["params"]["fields"]


@pytest.mark.asyncio
async def test_get_profile_by_id_404_returns_none() -> None:
    """get_profile_by_id returns None on 404 (no retry)."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=1,
    )
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=MagicMock(),
        response=mock_response,
    )
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        assert await client.get_profile_by_id("123") is None
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_get_profile_by_id_no_token() -> None:
    """get_profile_by_id returns None when no token."""
    client = HttpInstagramGraphApiClient(access_token="")
    assert await client.get_profile_by_id("123") is None


@pytest.mark.asyncio
async def test_get_profile_by_id_retry_succeeds_after_503() -> None:
    """get_profile_by_id retries on 503 and returns profile on second call."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=3,
        retry_delay_seconds=0.0,
    )
    error_response = MagicMock()
    error_response.status_code = 503
    error_response.text = "Unavailable"
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unavailable",
        request=MagicMock(),
        response=error_response,
    )
    success_response = MagicMock()
    success_response.json.return_value = {
        "username": "jane",
        "followers_count": 100,
    }
    success_response.raise_for_status.return_value = None
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [error_response, success_response]
        mock_client_class.return_value = mock_client
        info = await client.get_profile_by_id("123")
    assert info is not None
    assert info.username == "jane"
    assert info.followers_count == 100
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_profile_by_id_retry_succeeds_after_request_error() -> None:
    """get_profile_by_id retries on RequestError and returns profile."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=3,
        retry_delay_seconds=0.0,
    )
    success_response = MagicMock()
    success_response.json.return_value = {"username": "bob", "media_count": 5}
    success_response.raise_for_status.return_value = None
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [
            httpx.RequestError("Connection error"),
            success_response,
        ]
        mock_client_class.return_value = mock_client
        info = await client.get_profile_by_id("456")
    assert info is not None
    assert info.username == "bob"
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_profile_by_id_400_ig_business_scoped_id_fallback() -> None:
    """400 IGBusinessScopedID: fallback to username-only response."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=1,
    )
    error_400 = MagicMock()
    error_400.status_code = 400
    error_400.text = (
        '{"error":{"message":"Tried accessing nonexisting field '
        '(followers_count) on node type (IGBusinessScopedID)"}}'
    )
    error_400.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=MagicMock(),
        response=error_400,
    )
    success_username_only = MagicMock()
    success_username_only.json.return_value = {"username": "jane"}
    success_username_only.raise_for_status.return_value = None
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [error_400, success_username_only]
        mock_client_class.return_value = mock_client
        info = await client.get_profile_by_id("1624056105450070")
    assert info is not None
    assert info.username == "jane"
    assert info.followers_count is None
    assert info.media_count is None
    assert mock_client.get.call_count == 2
    second_call_params = mock_client.get.call_args_list[1][1]["params"]
    assert second_call_params["fields"] == "username"


@pytest.mark.asyncio
async def test_get_profile_by_id_400_business_discovery_full_profile() -> None:
    """When Business Discovery is configured, 400 IGBusinessScopedID uses it."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=1,
        business_account_id="17841405309211844",
        business_access_token="business_token",
    )
    error_400 = MagicMock()
    error_400.status_code = 400
    error_400.text = (
        '{"error":{"message":"Tried accessing nonexisting field '
        '(followers_count) on node type (IGBusinessScopedID)"}}'
    )
    error_400.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=MagicMock(),
        response=error_400,
    )
    username_response = MagicMock()
    username_response.json.return_value = {"username": "jane"}
    username_response.raise_for_status.return_value = None
    business_discovery_response = MagicMock()
    business_discovery_response.json.return_value = {
        "business_discovery": {
            "username": "jane",
            "followers_count": 100,
            "media_count": 50,
            "follows_count": 200,
        },
    }
    business_discovery_response.raise_for_status.return_value = None
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [
            error_400,
            username_response,
            business_discovery_response,
        ]
        mock_client_class.return_value = mock_client
        info = await client.get_profile_by_id("1624056105450070")
    assert info is not None
    assert info.username == "jane"
    assert info.followers_count == 100
    assert info.media_count == 50
    assert info.follows_count == 200
    assert mock_client.get.call_count == 3
    third_call_url = mock_client.get.call_args_list[2][0][0]
    assert "graph.facebook.com" in third_call_url
    assert "17841405309211844" in third_call_url
    third_call_params = mock_client.get.call_args_list[2][1]["params"]
    assert "business_discovery" in third_call_params["fields"]


@pytest.mark.asyncio
async def test_get_profile_by_id_400_username_fetch_fails_returns_none() -> (
    None
):
    """When 400 IGBusinessScopedID and username fetch fails, return None."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        retry_attempts=1,
    )
    error_400 = MagicMock()
    error_400.status_code = 400
    error_400.text = (
        '{"error":{"message":"Tried accessing nonexisting field '
        '(followers_count) on node type (IGBusinessScopedID)"}}'
    )
    error_400.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request",
        request=MagicMock(),
        response=error_400,
    )
    error_404 = MagicMock()
    error_404.status_code = 404
    error_404.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=MagicMock(),
        response=error_404,
    )
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = [error_400, error_404]
        mock_client_class.return_value = mock_client
        info = await client.get_profile_by_id("1624056105450070")
    assert info is None
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_get_profile_via_business_discovery_not_configured() -> None:
    """_get_profile_via_business_discovery returns None when not configured."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        business_account_id="",
        business_access_token=None,
    )
    info = await client._get_profile_via_business_discovery("jane")
    assert info is None


@pytest.mark.asyncio
async def test_get_profile_via_business_discovery_empty_username() -> None:
    """_get_profile_via_business_discovery returns None for empty username."""
    client = HttpInstagramGraphApiClient(
        access_token="token",
        business_account_id="17841",
        business_access_token="tok",
    )
    assert await client._get_profile_via_business_discovery("") is None
    assert await client._get_profile_via_business_discovery("  ") is None


@pytest.mark.asyncio
async def test_get_profile_by_id_no_username_in_response() -> None:
    """get_profile_by_id returns None when response has no username."""
    client = HttpInstagramGraphApiClient(access_token="token")
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "123"}
    mock_response.raise_for_status.return_value = None
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        assert await client.get_profile_by_id("123") is None


@pytest.mark.asyncio
async def test_get_profile_username_only_no_access_token_returns_none() -> None:
    """_get_profile_username_only returns None when access_token empty."""
    client = HttpInstagramGraphApiClient(access_token="")
    result = await client._get_profile_username_only("123456")
    assert result is None


@pytest.mark.asyncio
async def test_get_profile_via_business_discovery_http_error_returns_none() -> (
    None
):
    """_get_profile_via_business_discovery returns None on HTTPStatusError."""
    client = HttpInstagramGraphApiClient(
        access_token="tok",
        business_account_id="biz_id",
        business_access_token="biz_tok",
    )
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        error_response = MagicMock()
        error_response.status_code = 400
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=error_response
        )
        mock_client_class.return_value = mock_client
        result = await client._get_profile_via_business_discovery("test_user")
    assert result is None


@pytest.mark.asyncio
async def test_get_profile_via_business_discovery_no_discovery_key_returns_none() -> (  # noqa: E501
    None
):
    """_get_profile_via_business_discovery returns None when key missing."""
    client = HttpInstagramGraphApiClient(
        access_token="tok",
        business_account_id="biz_id",
        business_access_token="biz_tok",
    )
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_response = MagicMock()
        mock_response.json.return_value = {"some_key": "value"}
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        result = await client._get_profile_via_business_discovery("test_user")
    assert result is None


@pytest.mark.asyncio
async def test_in_memory_client_get_profile_by_id() -> None:
    """In-memory client get_profile_by_id uses profile_map or username_map."""
    full_profile = InstagramProfileInfo(
        username="full_user",
        followers_count=100,
        media_count=5,
    )
    client = InMemoryInstagramGraphApiClient(
        username_map={"uid2": "minimal_user"},
        profile_map={"uid1": full_profile},
    )
    info1 = await client.get_profile_by_id("uid1")
    assert info1 is not None
    assert info1.username == "full_user"
    assert info1.followers_count == 100

    info2 = await client.get_profile_by_id("uid2")
    assert info2 is not None
    assert info2.username == "minimal_user"
    assert info2.followers_count is None

    assert await client.get_profile_by_id("unknown") is None


@pytest.mark.asyncio
async def test_get_profile_by_id_raises_on_9010_error() -> None:
    """Error 9010 'No matching Instagram user' raises InstagramUserNotFoundError."""
    client = HttpInstagramGraphApiClient(
        access_token="test_token", retry_attempts=3
    )
    error_body = json.dumps({
        "error": {
            "message": "No matching Instagram user",
            "type": "IGApiException",
            "code": 9010,
        }
    })

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = error_body
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=mock_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        with pytest.raises(InstagramUserNotFoundError) as exc_info:
            await client.get_profile_by_id("123")
        assert exc_info.value.instagram_user_id == "123"
        # Should NOT retry — only 1 call
        assert mock_client.get.call_count == 1
