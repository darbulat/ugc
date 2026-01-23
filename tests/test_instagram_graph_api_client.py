"""Tests for Instagram Graph API client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from ugc_bot.infrastructure.instagram.graph_api_client import (
    HttpInstagramGraphApiClient,
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
    """Test username retrieval with HTTP error."""
    client = HttpInstagramGraphApiClient(access_token="test_token")

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


@pytest.mark.asyncio
async def test_get_username_by_id_request_error() -> None:
    """Test username retrieval with request error."""
    client = HttpInstagramGraphApiClient(access_token="test_token")

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.side_effect = httpx.RequestError("Connection error")
        mock_client_class.return_value = mock_client

        username = await client.get_username_by_id("123456")

        assert username is None


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
