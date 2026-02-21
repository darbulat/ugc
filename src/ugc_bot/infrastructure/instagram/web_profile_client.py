"""Instagram Web Profile API client (public web endpoint).

Uses curl_cffi to mimic browser TLS fingerprint (avoids 429 from Instagram
when Python/httpx is detected). Same IP with curl works; httpx gets 429.
"""

import logging
from typing import Any, Optional, Tuple, cast

from curl_cffi.requests import AsyncSession

from ugc_bot.application.ports import InstagramStatsProviderClient

logger = logging.getLogger(__name__)

WEB_PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_X_IG_APP_ID = "936619743392459"
TIMEOUT = 15.0
# Browser to impersonate (TLS/JA3); avoids 429 vs plain httpx.
IMPERSONATE = "chrome124"

# Headers that make the request look like a browser.
BROWSER_LIKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


class InstagramWebProfileClient(InstagramStatsProviderClient):
    """Client for Instagram web_profile_info (curl_cffi TLS impersonation)."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        x_ig_app_id: str = DEFAULT_X_IG_APP_ID,
        timeout: float = TIMEOUT,
        impersonate: str = IMPERSONATE,
    ) -> None:
        """Initialize web profile client.

        Args:
            user_agent: User-Agent header (browser-like).
            x_ig_app_id: X-IG-App-ID header (Instagram web app id).
            timeout: Request timeout in seconds.
            impersonate: curl_cffi browser to impersonate (TLS fingerprint).
        """
        self._user_agent = (user_agent or "").strip() or DEFAULT_USER_AGENT
        self._x_ig_app_id = (x_ig_app_id or "").strip() or DEFAULT_X_IG_APP_ID
        self._timeout = timeout
        self._impersonate = (impersonate or "").strip() or IMPERSONATE

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict]:
        """Fetch profile from web_profile_info; return raw JSON or None.

        Used when this client is in a multi-provider chain that calls
        get_profile_stats_by_username on each provider.
        """
        raw, _ = await self.get_profile_stats_with_provider(username)
        return raw

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Fetch profile from web_profile_info; return (raw, provider_id)."""
        if not username or not username.strip():
            return (None, "instagram_web")
        clean_username = username.strip()
        headers = {
            **BROWSER_LIKE_HEADERS,
            "User-Agent": self._user_agent,
            "X-IG-App-ID": self._x_ig_app_id,
        }
        params = {"username": clean_username}
        try:
            async with AsyncSession(
                timeout=self._timeout,
                impersonate=cast(Any, self._impersonate),
            ) as session:
                response = await session.get(
                    WEB_PROFILE_URL,
                    headers=headers,
                    params=params,
                )
                if response.status_code >= 400:
                    logger.warning(
                        "Instagram web profile request failed",
                        extra={
                            "username": clean_username,
                            "status_code": response.status_code,
                        },
                    )
                    return (None, "instagram_web")
                data = response.json()
        except Exception as exc:
            logger.warning(
                "Instagram web profile request error",
                extra={"username": clean_username, "error": str(exc)},
            )
            return (None, "instagram_web")
        if not isinstance(data, dict):
            return (None, "instagram_web")
        return (data, "instagram_web")
