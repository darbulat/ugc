"""Fetch Instagram profile stats via aiograpi (async private API).

Used as fallback when primary provider returns no data.
"""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _import_aiograpi():
    """Import aiograpi Client and exceptions. Return tuple or None."""
    _apply_httpx_proxies_compat()
    try:
        from aiograpi import Client  # type: ignore[import-untyped]
        from aiograpi.exceptions import (  # type: ignore[import-untyped]
            LoginRequired,
            UserNotFound,
        )

        try:
            from aiograpi.exceptions import (  # type: ignore[import-untyped]
                FeedbackRequired,
            )
        except ImportError:  # pragma: no cover
            FeedbackRequired = None  # type: ignore[misc, assignment]
        return Client, UserNotFound, LoginRequired, FeedbackRequired
    except ImportError:
        logger.warning("aiograpi not installed, cannot use aiograpi fallback")
        return None


def _apply_httpx_proxies_compat() -> None:
    """Make httpx.AsyncClient accept 'proxies' for aiograpi (httpx 0.28+).

    aiograpi passes proxies= to AsyncClient; httpx 0.28 uses proxy= (singular).
    """
    import httpx

    if getattr(httpx.AsyncClient, "_ugc_proxies_patched", False):
        return
    _orig_init = httpx.AsyncClient.__init__

    def _patched_init(
        self: httpx.AsyncClient, *args: Any, **kwargs: Any
    ) -> None:
        proxies = kwargs.pop("proxies", None)
        if proxies and "proxy" not in kwargs:
            if isinstance(proxies, dict):
                for _scheme, url in proxies.items():
                    if url:
                        kwargs["proxy"] = url
                        break
            elif isinstance(proxies, str):
                kwargs["proxy"] = proxies
        _orig_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = _patched_init  # type: ignore[method-assign]
    httpx.AsyncClient._ugc_proxies_patched = True  # type: ignore[attr-defined]


class AiograpiStatsFetcher:
    """Fetches Instagram profile stats via aiograpi (async private API)."""

    def __init__(
        self,
        instagram_username: str,
        instagram_password: str,
        session_path: Optional[Path] = None,
    ) -> None:
        self._instagram_username = instagram_username.strip()
        self._instagram_password = instagram_password
        self._session_path = (
            Path(session_path)
            if session_path
            else Path(".instagram_session.json")
        )
        self._disabled_reason: str | None = None

    def is_configured(self) -> bool:
        """Return True if credentials are set."""
        return bool(self._instagram_username and self._instagram_password)

    def _sessionid_from_client(self, cl) -> str | None:
        """Extract sessionid from loaded settings if present."""
        try:
            authorization_data = cl.settings.get("authorization_data", {})
            sessionid = authorization_data.get("sessionid")
        except Exception:
            return None
        if isinstance(sessionid, str) and len(sessionid) > 30:
            return sessionid
        return None

    async def _create_and_login_client(self, ClientCls):
        """Create Client, load session, authenticate. Return client or None."""
        if self._disabled_reason:
            return None

        cl = ClientCls()
        if self._session_path.exists():
            try:
                cl.load_settings(str(self._session_path))
            except Exception as e:
                logger.debug("Could not load aiograpi session: %s", e)

        sessionid = self._sessionid_from_client(cl)
        if sessionid:
            try:
                await cl.login_by_sessionid(sessionid)
                return cl
            except Exception as e:
                logger.warning("Aiograpi session auth failed: %s", e)
                self._disabled_reason = "session auth failed"
                return None

        try:
            await cl.login(self._instagram_username, self._instagram_password)
        except Exception as e:
            logger.warning("Aiograpi login failed: %s", e)
            self._disabled_reason = "password login failed"
            return None
        return cl

    async def _fetch_user_with_retry(
        self, cl, username_clean: str, ClientCls, UserNotFound, LoginRequired
    ):
        """Fetch user; on LoginRequired re-authenticate once and retry."""
        try:
            return await cl.user_info_by_username_v1(username_clean)
        except UserNotFound:
            return None
        except LoginRequired:
            logger.info("Aiograpi session expired, re-authenticating...")
            cl = await self._create_and_login_client(ClientCls)
            if cl is None:
                return None
            try:
                return await cl.user_info_by_username_v1(username_clean)
            except Exception as inner_e:
                logger.warning("Aiograpi re-auth or fetch failed: %s", inner_e)
                self._disabled_reason = "re-auth failed"
                return None

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict[str, Any]]:
        """Fetch profile stats for username.

        Returns raw dict compatible with stats extraction, or None.
        """
        if not self.is_configured() or self._disabled_reason:
            return None

        imp = _import_aiograpi()
        if imp is None:
            return None
        ClientCls, UserNotFound, LoginRequired, FeedbackRequired = imp

        cl = await self._create_and_login_client(ClientCls)
        if cl is None:
            return None

        username_clean = username.strip().lower()
        try:
            user = await self._fetch_user_with_retry(
                cl, username_clean, ClientCls, UserNotFound, LoginRequired
            )
        except Exception as e:
            if FeedbackRequired is not None and isinstance(e, FeedbackRequired):
                logger.warning(
                    "Instagram rate limit or feedback required for %s: %s",
                    username,
                    e,
                )
                self._disabled_reason = "feedback required"
                return None
            self._disabled_reason = "unexpected fetch error"
            raise

        if user is None:
            return None

        try:
            cl.dump_settings(str(self._session_path))
        except OSError as e:
            logger.debug("Could not save aiograpi session: %s", e)

        return {
            "data": {
                "username": user.username,
                "followers_count": user.follower_count,
                "follows_count": user.following_count,
                "media_count": user.media_count,
                "biography": user.biography or "",
            },
            "id": str(user.pk),
        }
