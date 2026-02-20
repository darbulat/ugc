"""Rapid API client for Instagram profile/stats by username."""

import logging
from typing import Optional

import httpx

from ugc_bot.application.ports import InstagramRapidApiClient

logger = logging.getLogger(__name__)

RAPIDAPI_BASE_URL = "https://{host}.rapidapi.com"
DEFAULT_PROFILE_PATH = "/user/details-by-username"
RAPIDAPI_TIMEOUT = 15.0


class HttpInstagramRapidApiClient(InstagramRapidApiClient):
    """HTTP client for Rapid API Instagram profile by username."""

    def __init__(
        self,
        api_key: str,
        host: str,
        path: str = DEFAULT_PROFILE_PATH,
        timeout: float = RAPIDAPI_TIMEOUT,
    ) -> None:
        """Initialize Rapid API client.

        Args:
            api_key: X-RapidAPI-Key header value.
            host: API host name (e.g. instagram-v2, instagram-statistics-api).
            path: Request path (e.g. /user/details-by-username).
            timeout: Request timeout in seconds.
        """
        self._api_key = (api_key or "").strip()
        self._host = (host or "").strip()
        self._path = (path or DEFAULT_PROFILE_PATH).strip().rstrip("/")
        self._timeout = timeout
        self._base_url = (
            RAPIDAPI_BASE_URL.format(host=self._host) if self._host else ""
        )

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
        url = f"{self._base_url}{self._path}"
        headers = {
            "X-RapidAPI-Key": self._api_key,
            "X-RapidAPI-Host": self._host,
        }
        params = {"username": clean_username}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
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
