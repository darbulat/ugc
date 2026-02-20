"""Service for periodic update of Instagram profile statistics."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramGraphApiClient,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


class InstagramStatsUpdateService:
    """Update Instagram followers/media stats for confirmed blogger profiles."""

    def __init__(
        self,
        blogger_repo: BloggerProfileRepository,
        instagram_api_client: Optional[InstagramGraphApiClient] = None,
        transaction_manager: Optional[TransactionManager] = None,
        batch_size: int = 50,
        delay_seconds: float = 1.0,
    ) -> None:
        """Initialize the service.

        Args:
            blogger_repo: Repository for blogger profiles.
            instagram_api_client: Instagram Graph API client (optional).
            transaction_manager: Optional transaction manager for saves.
            batch_size: Max profiles to process per run.
            delay_seconds: Delay between API requests to respect rate limits.
        """
        self.blogger_repo = blogger_repo
        self.instagram_api_client = instagram_api_client
        self.transaction_manager = transaction_manager
        self._batch_size = batch_size
        self._delay_seconds = delay_seconds

    async def run_once(self) -> tuple[int, int]:
        """Fetch and update Instagram stats for one batch of profiles.

        Returns:
            Tuple of (updated_count, error_count).
        """
        if not self.instagram_api_client:
            logger.warning(
                "Instagram API client not configured, skipping update"
            )
            return (0, 0)

        async def _list(session: object | None):
            return await self.blogger_repo.list_confirmed_with_instagram_id(
                limit=self._batch_size,
                offset=0,
                session=session,
            )

        profiles = await with_optional_tx(self.transaction_manager, _list)
        if not profiles:
            logger.debug(
                "No confirmed profiles with instagram_user_id to update"
            )
            return (0, 0)

        updated = 0
        errors = 0
        now = datetime.now(timezone.utc)

        for profile in profiles:
            ig_id = profile.instagram_user_id or ""
            try:
                info = await self.instagram_api_client.get_profile_by_id(ig_id)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch Instagram profile",
                    extra={
                        "user_id": str(profile.user_id),
                        "instagram_user_id": ig_id,
                        "error": str(exc),
                    },
                    exc_info=exc,
                )
                errors += 1
                continue

            if info is None:
                logger.debug(
                    "No profile data returned",
                    extra={
                        "user_id": str(profile.user_id),
                        "instagram_user_id": ig_id,
                    },
                )
                errors += 1
                continue

            instagram_url = (
                f"https://instagram.com/{info.username}"
                if info.username
                else profile.instagram_url
            )

            updated_profile = replace(
                profile,
                instagram_url=instagram_url,
                instagram_followers_count=info.followers_count,
                instagram_media_count=info.media_count,
                instagram_follows_count=info.follows_count,
                instagram_biography=info.biography,
                instagram_username=info.username,
                instagram_stats_fetched_at=now,
            )

            async def _save(
                session: object | None,
                profile_to_save: BloggerProfile = updated_profile,
            ) -> None:
                await self.blogger_repo.save(profile_to_save, session=session)

            await with_optional_tx(self.transaction_manager, _save)
            updated += 1
            logger.debug(
                "Updated Instagram stats",
                extra={
                    "user_id": str(profile.user_id),
                    "followers": info.followers_count,
                },
            )
            await asyncio.sleep(self._delay_seconds)

        return (updated, errors)
