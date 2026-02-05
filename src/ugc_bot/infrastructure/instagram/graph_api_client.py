"""Instagram Graph API client implementation."""

import logging

import httpx

from ugc_bot.application.ports import InstagramGraphApiClient

logger = logging.getLogger(__name__)


class HttpInstagramGraphApiClient(InstagramGraphApiClient):
    """HTTP client for Instagram Graph API."""

    def __init__(
        self,
        access_token: str,
        base_url: str = "https://graph.instagram.com",
        api_version: str = "v24.0",
        timeout: float = 10.0,
    ) -> None:
        """Initialize Instagram Graph API client.

        Args:
            access_token: Instagram access token
            base_url: Base URL for Instagram Graph API
            api_version: API version (default: v24.0)
            timeout: Request timeout in seconds
        """
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout

    async def get_username_by_id(self, instagram_user_id: str) -> str | None:
        """Get Instagram username by user ID.

        Uses Instagram Graph API endpoint:
        GET /{ig-user-id}?fields=username&access_token={access-token}

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
