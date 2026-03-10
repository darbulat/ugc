"""ScrapeCreators API client for Instagram profile by handle."""

import asyncio
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
SCRAPECREATORS_RETRY_ATTEMPTS = 3
SCRAPECREATORS_RETRY_BACKOFF_SECONDS = (1.0, 2.0)


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

        Retries on 5xx with exponential backoff. Returns full response dict
        (success, data.user, status) or None on error.
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

        last_exc: Optional[ScrapeCreatorsAPIError] = None
        backoff = (0.0,) + SCRAPECREATORS_RETRY_BACKOFF_SECONDS

        for attempt in range(SCRAPECREATORS_RETRY_ATTEMPTS):
            if attempt > 0:
                await asyncio.sleep(backoff[attempt])
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        request_url, headers=headers, params=params
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                response_snippet = (exc.response.text or "")[:200]
                logger.error(
                    "ScrapeCreators request failed",
                    extra={
                        "handle": clean_handle,
                        "status_code": status_code,
                        "response": response_snippet,
                        "attempt": attempt + 1,
                        "max_attempts": SCRAPECREATORS_RETRY_ATTEMPTS,
                    },
                )
                last_exc = ScrapeCreatorsAPIError(
                    f"ScrapeCreators API error: {status_code}",
                    status_code=status_code,
                    response_text=exc.response.text or "",
                )
                if (
                    status_code >= 500
                    and attempt < SCRAPECREATORS_RETRY_ATTEMPTS - 1
                ):
                    continue
                raise last_exc from exc
            except (httpx.RequestError, ValueError) as exc:
                logger.warning(
                    "ScrapeCreators request error",
                    extra={"handle": clean_handle, "error": str(exc)},
                )
                return None

        return self._validate_profile_response(data, clean_handle)

    def _validate_profile_response(
        self, data: object, handle: str
    ) -> Optional[dict]:
        """Return response dict if valid, else None."""
        if not isinstance(data, dict):
            logger.debug(
                "ScrapeCreators response is not a dict",
                extra={"handle": handle},
            )
            return None
        if not data.get("success") or "data" not in data:
            logger.debug(
                "ScrapeCreators response missing success or data",
                extra={"handle": handle},
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
