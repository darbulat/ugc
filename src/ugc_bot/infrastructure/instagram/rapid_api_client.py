"""Rapid API client for Instagram profile/stats by username."""

import logging
from typing import List, Optional, Tuple

import httpx

from ugc_bot.application.ports import (
    InstagramRapidApiClient,
    InstagramStatsProviderClient,
    RapidApiRateLimitError,
)

logger = logging.getLogger(__name__)

RAPIDAPI_BASE_URL = "https://{host}.rapidapi.com"
DEFAULT_PROFILE_PATH = "/user/details-by-username"
INSTAGRAM_PROFILE_URL_PREFIX = "https://www.instagram.com/"
RAPIDAPI_TIMEOUT = 15.0


class HttpInstagramRapidApiClient(InstagramRapidApiClient):
    """HTTP client for Rapid API Instagram profile by username."""

    def __init__(
        self,
        api_key: str,
        host: str,
        path: str = DEFAULT_PROFILE_PATH,
        param_style: str = "username",
        timeout: float = RAPIDAPI_TIMEOUT,
    ) -> None:
        """Initialize Rapid API client.

        Args:
            api_key: X-RapidAPI-Key header value.
            host: API host name (e.g. instagram-statistics-api).
            path: Request path (e.g. /community).
            param_style: "username" (query param username) or "url" (query
                param url with full profile URL, for instagram-statistics-api).
            timeout: Request timeout in seconds.
        """
        self._api_key = (api_key or "").strip()
        self._host = (host or "").strip()
        self._path = (path or DEFAULT_PROFILE_PATH).strip().rstrip("/")
        self._param_style = (
            param_style or "username"
        ).strip().lower() or "username"
        self._timeout = timeout
        if not self._host:
            self._base_url = ""
        elif "rapidapi.com" in self._host:
            self._base_url = f"https://{self._host}"
        else:
            self._base_url = RAPIDAPI_BASE_URL.format(host=self._host)

    def _is_configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict]:
        """Fetch full profile/stats response for username.

        Returns raw JSON response or None on error / not found.
        """
        if not self._is_configured():
            logger.warning("Rapid API client not configured (key or host)")
            return None
        if not username or not username.strip():
            return None

        clean_username = username.strip()
        request_url = f"{self._base_url}{self._path}"
        headers = {
            "X-RapidAPI-Key": self._api_key,
            "X-RapidAPI-Host": self._host,
        }
        if self._param_style == "url":
            params = {"url": f"{INSTAGRAM_PROFILE_URL_PREFIX}{clean_username}/"}
        else:
            params = {"username": clean_username}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    request_url, headers=headers, params=params
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RapidApiRateLimitError(
                    "Rapid API rate limit (429)"
                ) from exc
            logger.warning(
                "Rapid API request failed",
                extra={
                    "username": clean_username,
                    "status_code": exc.response.status_code,
                    "response": (exc.response.text or "")[:200],
                },
            )
            return None
        except (httpx.RequestError, ValueError) as exc:
            logger.warning(
                "Rapid API request error",
                extra={"username": clean_username, "error": str(exc)},
            )
            return None

        if not isinstance(data, dict):
            logger.debug(
                "Rapid API response is not a dict",
                extra={"username": clean_username},
            )
            return None

        return data


class SingleProviderWrapper(InstagramStatsProviderClient):
    """Wraps one Rapid API client and returns stats with fixed provider id."""

    def __init__(
        self,
        client: InstagramRapidApiClient,
        provider_id: str = "rapid_api",
    ) -> None:
        self._client = client
        self._provider_id = provider_id

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Call underlying client; return (data, provider_id)."""
        data = await self._client.get_profile_stats_by_username(username)
        return (data, self._provider_id)


class MultiProviderInstagramStatsClient(InstagramStatsProviderClient):
    """Tries multiple providers in order; on 429 uses the next provider."""

    def __init__(
        self,
        clients_with_ids: List[Tuple[InstagramRapidApiClient, str]],
    ) -> None:
        """Initialize with list of (client, provider_id)."""
        self._clients = clients_with_ids

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Try each provider; on RapidApiRateLimitError try next."""
        last_provider = ""
        for client, provider_id in self._clients:
            last_provider = provider_id
            try:
                data = await client.get_profile_stats_by_username(username)
                return (data, provider_id)
            except RapidApiRateLimitError:
                logger.info(
                    "Rapid API rate limit, trying next provider",
                    extra={"provider": provider_id, "username": username},
                )
                continue
        return (None, last_provider)
