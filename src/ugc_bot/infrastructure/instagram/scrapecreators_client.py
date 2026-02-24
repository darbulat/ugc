"""ScrapeCreators API client for Instagram profile by handle."""

import logging
from typing import Optional, Tuple

import httpx

from ugc_bot.application.errors import ScrapeCreatorsAPIError
from ugc_bot.application.ports import (
    InstagramRapidApiClient,
    InstagramStatsProviderClient,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.scrapecreators.com"
DEFAULT_PROFILE_PATH = "/v1/instagram/profile"
SCRAPECREATORS_TIMEOUT = 15.0


class ScrapeCreatorsProfileClient(
    InstagramStatsProviderClient, InstagramRapidApiClient
):
    """HTTP client for ScrapeCreators Instagram profile API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        path: str = DEFAULT_PROFILE_PATH,
        timeout: float = SCRAPECREATORS_TIMEOUT,
    ) -> None:
        """Initialize ScrapeCreators client.

        Args:
            api_key: x-api-key header value.
            base_url: API base URL (no trailing slash).
            path: Request path (e.g. /v1/instagram/profile).
            timeout: Request timeout in seconds.
        """
        self._api_key = (api_key or "").strip()
        base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self._base_url = base or DEFAULT_BASE_URL
        self._path = (path or DEFAULT_PROFILE_PATH).strip().rstrip("/")
        self._timeout = timeout

    def _is_configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    async def get_profile(
        self, handle: str, *, trim: bool = False
    ) -> Optional[dict]:
        """Fetch Instagram profile for handle.

        Returns full response dict (success, data.user, status) or None on
        error.
        """
        if not self._is_configured():
            logger.warning(
                "ScrapeCreators client not configured (api_key or base_url)"
            )
            return None
        if not handle or not handle.strip():
            return None

        clean_handle = handle.strip()
        request_url = f"{self._base_url}{self._path}"
        headers = {"x-api-key": self._api_key}
        params: dict = {"handle": clean_handle}
        if trim:
            params["trim"] = "true"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    request_url, headers=headers, params=params
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            response_snippet = (exc.response.text or "")[:200]
            logger.error(
                "ScrapeCreators request failed",
                extra={
                    "handle": clean_handle,
                    "status_code": status_code,
                    "response": response_snippet,
                },
            )
            raise ScrapeCreatorsAPIError(
                f"ScrapeCreators API error: {status_code}",
                status_code=status_code,
                response_text=exc.response.text or "",
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            logger.warning(
                "ScrapeCreators request error",
                extra={"handle": clean_handle, "error": str(exc)},
            )
            return None

        if not isinstance(data, dict):
            logger.debug(
                "ScrapeCreators response is not a dict",
                extra={"handle": clean_handle},
            )
            return None
        if not data.get("success") or "data" not in data:
            logger.debug(
                "ScrapeCreators response missing success or data",
                extra={"handle": clean_handle},
            )
            return None

        return data

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict]:
        """Fetch profile; alias for get_profile for provider chain."""
        return await self.get_profile(username, trim=False)

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Fetch profile; return (full response dict, provider_id)."""
        data = await self.get_profile(username, trim=False)
        return (data, "scrapecreators")
