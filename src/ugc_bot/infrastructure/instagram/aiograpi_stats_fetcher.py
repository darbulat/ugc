"""Fetch Instagram profile stats via aiograpi (async private API). Used as fallback when primary provider returns no data."""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


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
            Path(session_path) if session_path else Path(".instagram_session.json")
        )

    def is_configured(self) -> bool:
        """Return True if credentials are set."""
        return bool(self._instagram_username and self._instagram_password)

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict[str, Any]]:
        """Fetch profile stats for username. Returns raw dict compatible with stats extraction, or None."""
        if not self.is_configured():
            return None
        try:
            from aiograpi import Client
            from aiograpi.exceptions import LoginRequired, UserNotFound
        except ImportError:
            logger.warning("aiograpi not installed, cannot use aiograpi fallback")
            return None

        cl = Client()
        if self._session_path.exists():
            try:
                cl.load_settings(str(self._session_path))
            except Exception as e:
                logger.debug("Could not load aiograpi session: %s", e)

        try:
            await cl.login(self._instagram_username, self._instagram_password)
        except Exception as e:
            logger.warning("Aiograpi login failed: %s", e)
            return None

        try:
            user = await cl.user_info_by_username_v1(username.strip().lower())
        except UserNotFound:
            return None
        except LoginRequired:
            logger.info("Aiograpi session expired, re-logging in...")
            cl = Client()
            try:
                await cl.login(self._instagram_username, self._instagram_password)
                user = await cl.user_info_by_username_v1(username.strip().lower())
            except Exception as e:
                logger.warning("Aiograpi re-login or fetch failed: %s", e)
                return None
            try:
                cl.dump_settings(str(self._session_path))
            except OSError as e:
                logger.debug("Could not save aiograpi session: %s", e)
        else:
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
