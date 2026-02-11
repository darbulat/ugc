"""Instagram Graph API client implementation."""

import asyncio
import logging

import httpx

from ugc_bot.application.ports import InstagramGraphApiClient

logger = logging.getLogger(__name__)

INSTAGRAM_GRAPH_API_RETRY_ATTEMPTS = 3
INSTAGRAM_GRAPH_API_RETRY_DELAY_SECONDS = 1.0


def _is_retriable_status(status_code: int) -> bool:
    """Return True for 429 or 5xx (transient/rate-limit errors)."""
    return status_code == 429 or 500 <= status_code < 600


class HttpInstagramGraphApiClient(InstagramGraphApiClient):
    """HTTP client for Instagram Graph API with retry on transient errors."""

    def __init__(
        self,
        access_token: str,
        base_url: str = "https://graph.instagram.com",
        api_version: str = "v24.0",
        timeout: float = 10.0,
        retry_attempts: int = INSTAGRAM_GRAPH_API_RETRY_ATTEMPTS,
        retry_delay_seconds: float = INSTAGRAM_GRAPH_API_RETRY_DELAY_SECONDS,
    ) -> None:
        """Initialize Instagram Graph API client.

        Args:
            access_token: Instagram access token
            base_url: Base URL for Instagram Graph API
            api_version: API version (default: v24.0)
            timeout: Request timeout in seconds
            retry_attempts: Max attempts on retriable errors (default: 3)
            retry_delay_seconds: Delay between retries in seconds (default: 1.0)
        """
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_delay_seconds = retry_delay_seconds

    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID.

        Uses Instagram Graph API endpoint:
        GET /{ig-user-id}?fields=username&access_token={access-token}

        Retries on RequestError (network) and on 429 / 5xx responses.

        Args:
            instagram_user_id: Instagram-scoped user ID (sender_id from webhook)

        Returns:
            Username if found, None otherwise
        """
        if not self.access_token:
            logger.warning("Instagram access token not configured")
            return None

        url = f"{self.base_url}/{self.api_version}/{instagram_user_id}"
        params = {
            "fields": "username",
            "access_token": self.access_token,
        }

        for attempt in range(1, self._retry_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()

                username = data.get("username")
                if username:
                    logger.info(
                        "Retrieved Instagram username",
                        extra={
                            "instagram_user_id": instagram_user_id,
                            "username": username,
                        },
                    )
                    return username
                logger.warning(
                    "Username not found in API response",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "response": data,
                    },
                )
                return None

            except httpx.HTTPStatusError as exc:
                if (
                    _is_retriable_status(exc.response.status_code)
                    and attempt < self._retry_attempts
                ):
                    logger.warning(
                        "Instagram API request failed, retrying",
                        extra={
                            "instagram_user_id": instagram_user_id,
                            "status_code": exc.response.status_code,
                            "attempt": attempt,
                        },
                    )
                    await asyncio.sleep(self._retry_delay_seconds)
                    continue
                logger.warning(
                    "Instagram API request failed",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "status_code": exc.response.status_code,
                        "response": exc.response.text[:200],
                    },
                )
                return None
            except httpx.RequestError as exc:
                if attempt < self._retry_attempts:
                    logger.warning(
                        "Instagram API request error, retrying",
                        extra={
                            "instagram_user_id": instagram_user_id,
                            "error": str(exc),
                            "attempt": attempt,
                        },
                    )
                    await asyncio.sleep(self._retry_delay_seconds)
                    continue
                logger.warning(
                    "Instagram API request error",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "error": str(exc),
                    },
                )
                return None
            except Exception as exc:  # pragma: no cover
                logger.exception(
                    "Unexpected error getting Instagram username",
                    extra={"instagram_user_id": instagram_user_id},
                    exc_info=exc,
                )
                return None

        return None  # pragma: no cover - unreachable, satisfies RET503
