"""Instagram Graph API client implementation."""

import asyncio
import logging
from typing import Optional

import httpx

from ugc_bot.application.ports import (
    InstagramGraphApiClient,
    InstagramProfileInfo,
)
from ugc_bot.infrastructure.instagram.delays import random_delay_seconds

logger = logging.getLogger(__name__)

INSTAGRAM_GRAPH_API_RETRY_ATTEMPTS = 3
INSTAGRAM_GRAPH_API_RETRY_DELAY_SECONDS = 1.0
INSTAGRAM_PROFILE_FIELDS = "username,follower_count,profile_pic,name"
INSTAGRAM_USERNAME_ONLY_FIELDS = "username"

BUSINESS_DISCOVERY_FIELDS = (
    "username,followers_count,media_count,follows_count,biography,"
    "has_profile_pic"
)
FACEBOOK_GRAPH_BASE_URL = "https://graph.facebook.com"


def _is_ig_business_scoped_id_error(response_text: str) -> bool:
    """True if error says node is IGBusinessScopedID (no stats fields)."""
    return (
        "IGBusinessScopedID" in response_text
        or "nonexisting field" in response_text.lower()
    )


def _is_retriable_status(status_code: int) -> bool:
    """Return True for 429 or 5xx (transient/rate-limit errors)."""
    return status_code == 429 or 500 <= status_code < 600


def _int_from_data(obj: dict, *keys: str) -> Optional[int]:
    """First non-None int for given keys (e.g. follower_count)."""
    for key in keys:
        val = obj.get(key)
        if val is None:
            continue
        try:
            return int(val)
        except (TypeError, ValueError):
            continue
    return None


def _bool_from_data(obj: dict, bool_key: str, str_key: str) -> Optional[bool]:
    """Return bool from bool_key, or True if str_key is non-empty string."""
    val = obj.get(bool_key)
    if val is not None:
        return bool(val)
    s = obj.get(str_key)
    if isinstance(s, str) and s.strip():
        return True
    return None


def _parse_profile_response(
    data: dict,
) -> Optional[InstagramProfileInfo]:
    """Parse API response into InstagramProfileInfo. None if no username.

    Accepts both Graph API names (followers_count, has_profile_pic) and
    alternate names (follower_count, profile_pic URL).
    """
    username = data.get("username")
    if not username:
        return None

    followers_count = _int_from_data(data, "followers_count", "follower_count")
    media_count = _int_from_data(data, "media_count")
    follows_count = _int_from_data(data, "follows_count")
    biography = data.get("biography") or None
    has_profile_pic = _bool_from_data(data, "has_profile_pic", "profile_pic")

    return InstagramProfileInfo(
        username=username,
        followers_count=followers_count,
        media_count=media_count,
        follows_count=follows_count,
        biography=biography,
        has_profile_pic=has_profile_pic,
    )


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
        business_account_id: Optional[str] = None,
        business_access_token: Optional[str] = None,
        facebook_graph_base_url: str = FACEBOOK_GRAPH_BASE_URL,
    ) -> None:
        """Initialize Instagram Graph API client.

        Args:
            access_token: Instagram access token (webhook / app).
            base_url: Base URL for Instagram Graph API.
            api_version: API version (default: v24.0).
            timeout: Request timeout in seconds.
            retry_attempts: Max attempts on retriable errors (default: 3).
            retry_delay_seconds: Delay between retries (default: 1.0).
            business_account_id: IG User ID for Business Discovery (optional).
            business_access_token: Token with instagram_business_basic (opt).
            facebook_graph_base_url: Base URL for Facebook Graph.
        """
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._business_account_id = (business_account_id or "").strip() or None
        self._business_access_token = (
            business_access_token or ""
        ).strip() or None
        self._facebook_graph_base_url = facebook_graph_base_url.rstrip("/")

    async def _get_profile_username_only(
        self, instagram_user_id: str
    ) -> Optional[InstagramProfileInfo]:
        """Fetch only username (IGBusinessScopedID nodes). Stats stay None."""
        if not self.access_token:
            return None
        url = f"{self.base_url}/{self.api_version}/{instagram_user_id}"
        params = {
            "fields": INSTAGRAM_USERNAME_ONLY_FIELDS,
            "access_token": self.access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPStatusError, httpx.RequestError):
            return None
        return _parse_profile_response(data)

    async def _get_profile_via_business_discovery(
        self, username: str
    ) -> Optional[InstagramProfileInfo]:
        """Fetch full profile via Business Discovery (Facebook Graph API).

        Requires _business_account_id and _business_access_token.
        Returns None if not configured or request fails.
        """
        if not self._business_account_id or not self._business_access_token:
            return None
        if not username or not username.strip():
            return None
        username_clean = username.strip()
        url = (
            f"{self._facebook_graph_base_url}/{self.api_version}"
            f"/{self._business_account_id}"
        )
        fields_value = (
            f"business_discovery.username({username_clean})"
            f"{{{BUSINESS_DISCOVERY_FIELDS}}}"
        )
        params = {
            "fields": fields_value,
            "access_token": self._business_access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.debug(
                "Business Discovery request failed for username=%s: %s",
                username_clean,
                exc,
            )
            return None
        discovery = data.get("business_discovery")
        if not discovery or not isinstance(discovery, dict):
            return None
        discovery.setdefault("username", username_clean)
        return _parse_profile_response(discovery)

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
                    await asyncio.sleep(
                        random_delay_seconds(self._retry_delay_seconds)
                    )
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
                    await asyncio.sleep(
                        random_delay_seconds(self._retry_delay_seconds)
                    )
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

    async def _handle_profile_400_ig_business_scoped(
        self, instagram_user_id: str
    ) -> Optional[InstagramProfileInfo]:
        """On 400 IGBusinessScopedID: username-only then Business Discovery."""
        username_info = await self._get_profile_username_only(instagram_user_id)
        if username_info is None:
            return None
        if self._business_account_id and self._business_access_token:
            full_info = await self._get_profile_via_business_discovery(
                username_info.username
            )
            if full_info is not None:
                logger.info(
                    "Got profile via Business Discovery",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "username": full_info.username,
                    },
                )
                return full_info
        logger.debug(
            "Got username only (IGBusinessScopedID); "
            "stats unavailable for this node type",
            extra={"instagram_user_id": instagram_user_id},
        )
        return username_info

    async def get_profile_by_id(
        self, instagram_user_id: str
    ) -> Optional[InstagramProfileInfo]:
        """Get full profile (username, counts, biography) by user ID.

        Uses Instagram Graph API:
        GET /{ig-user-id}?fields=username,followers_count,...

        Retries on RequestError and on 429 / 5xx responses.

        Args:
            instagram_user_id: Instagram-scoped user ID (sender_id from webhook)

        Returns:
            Profile info if username present, None otherwise
        """
        if not self.access_token:
            logger.warning("Instagram access token not configured")
            return None

        url = f"{self.base_url}/{self.api_version}/{instagram_user_id}"
        params = {
            "fields": INSTAGRAM_PROFILE_FIELDS,
            "access_token": self.access_token,
        }

        for attempt in range(1, self._retry_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()

                info = _parse_profile_response(data)
                if info is None:
                    logger.warning(
                        "Username not found in API response",
                        extra={
                            "instagram_user_id": instagram_user_id,
                            "response": data,
                        },
                    )
                    return None

                logger.debug(
                    "Retrieved Instagram profile",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "username": info.username,
                    },
                )
                return info

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
                    await asyncio.sleep(
                        random_delay_seconds(self._retry_delay_seconds)
                    )
                    continue
                if (
                    exc.response.status_code == 400
                    and _is_ig_business_scoped_id_error(exc.response.text)
                ):
                    return await self._handle_profile_400_ig_business_scoped(
                        instagram_user_id
                    )
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
                    await asyncio.sleep(
                        random_delay_seconds(self._retry_delay_seconds)
                    )
                    continue
                logger.warning(  # pragma: no cover - exhausted retries
                    "Instagram API request error",
                    extra={
                        "instagram_user_id": instagram_user_id,
                        "error": str(exc),
                    },
                )
                return None  # pragma: no cover - RequestError after retries
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    "Unexpected error getting Instagram profile",
                    extra={"instagram_user_id": instagram_user_id},
                    exc_info=exc,
                )
                return None  # pragma: no cover

        return None  # pragma: no cover - unreachable, satisfies RET503
