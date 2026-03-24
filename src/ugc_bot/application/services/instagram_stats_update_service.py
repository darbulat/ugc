"""Service for periodic update of Instagram profile statistics."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from ugc_bot.application.delays import random_delay_seconds
from ugc_bot.application.errors import InstagramUserNotFoundError
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
        user_repo=None,
        messenger_client=None,
        bot_texts_service=None,
        default_locale: str = "ru",
    ) -> None:
        """Initialize the service.

        Args:
            blogger_repo: Repository for blogger profiles.
            instagram_api_client: Instagram Graph API client (optional).
            transaction_manager: Optional transaction manager for saves.
            batch_size: Max profiles to process per run.
            delay_seconds: Delay between API requests to respect rate limits.
            user_repo: Optional user repository for notifications.
            messenger_client: Optional messenger for notifications.
            bot_texts_service: Optional localized texts service.
            default_locale: Default locale for messages.
        """
        self.blogger_repo = blogger_repo
        self.instagram_api_client = instagram_api_client
        self.transaction_manager = transaction_manager
        self._batch_size = batch_size
        self._delay_seconds = delay_seconds
        self.user_repo = user_repo
        self.messenger_client = messenger_client
        self.bot_texts_service = bot_texts_service
        self._default_locale = default_locale

    async def _handle_user_not_found(
        self, profile: BloggerProfile, instagram_user_id: str
    ) -> None:
        """Unconfirm blogger and notify user when Instagram account is lost."""
        updated_profile = replace(profile, confirmed=False)

        async def _save_unconfirmed(
            session: object | None,
            p: BloggerProfile = updated_profile,
        ) -> None:
            if p.location_geometry is None:
                current = await self.blogger_repo.get_by_user_id(
                    p.user_id, session=session
                )
                if current is not None and current.location_geometry:
                    p = replace(p, location_geometry=current.location_geometry)
            await self.blogger_repo.save(p, session=session)

        await with_optional_tx(self.transaction_manager, _save_unconfirmed)

        logger.warning(
            "Blogger unconfirmed: Instagram account not found",
            extra={
                "user_id": str(profile.user_id),
                "instagram_user_id": instagram_user_id,
            },
        )

        if self.user_repo is None or self.messenger_client is None:
            return

        async def _get_user(session: object | None):
            return await self.user_repo.get_by_id(
                profile.user_id, session=session
            )

        user = await with_optional_tx(self.transaction_manager, _get_user)
        if user is None or not user.telegram_id:
            return

        locale = getattr(user, "language", None) or self._default_locale
        if self.bot_texts_service is not None:
            text = await self.bot_texts_service.get(
                "msg_instagram_account_lost", locale
            )
        else:
            text = ""
        if not text:
            text = (
                "Ваш Instagram-аккаунт был удалён или изменён. "
                "Для получения заказов отредактируйте профиль "
                "и пройдите верификацию заново."
            )

        try:
            await self.messenger_client.send_text(
                chat_id=user.telegram_id, text=text
            )
        except Exception as exc:
            logger.warning(
                "Failed to notify user about Instagram account loss",
                extra={
                    "user_id": str(profile.user_id),
                    "error": str(exc),
                },
            )

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
            ok = await self._process_profile(profile, now)
            if ok:
                updated += 1
            else:
                errors += 1

        return (updated, errors)

    async def _process_profile(
        self, profile: BloggerProfile, now: datetime
    ) -> bool:
        """Process a single profile. Return True if updated, False on error."""
        assert self.instagram_api_client is not None
        ig_id = profile.instagram_user_id or ""
        try:
            info = await self.instagram_api_client.get_profile_by_id(ig_id)
        except InstagramUserNotFoundError:
            logger.warning(
                "Instagram user not found (9010), unconfirming",
                extra={
                    "user_id": str(profile.user_id),
                    "instagram_user_id": ig_id,
                },
            )
            await self._handle_user_not_found(profile, ig_id)
            return False
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
            return False

        if info is None:
            logger.debug(
                "No profile data returned",
                extra={
                    "user_id": str(profile.user_id),
                    "instagram_user_id": ig_id,
                },
            )
            return False

        instagram_url = (
            f"https://instagram.com/{info.username}"
            if info.username
            else profile.instagram_url
        )

        updated_profile = replace(
            profile,
            instagram_url=instagram_url,
            instagram_followers_count=info.followers_count,
            instagram_username=info.username,
            instagram_stats_fetched_at=now,
        )

        async def _save(
            session: object | None,
            profile_to_save: BloggerProfile = updated_profile,
        ) -> None:
            # Preserve geometry when entity has None (stats-only update).
            if profile_to_save.location_geometry is None:
                current = await self.blogger_repo.get_by_user_id(
                    profile_to_save.user_id, session=session
                )
                if current is not None and current.location_geometry:
                    profile_to_save = replace(
                        profile_to_save,
                        location_geometry=current.location_geometry,
                    )
            await self.blogger_repo.save(profile_to_save, session=session)

        await with_optional_tx(self.transaction_manager, _save)
        logger.debug(
            "Updated Instagram stats",
            extra={
                "user_id": str(profile.user_id),
                "followers": info.followers_count,
            },
        )
        await asyncio.sleep(random_delay_seconds(self._delay_seconds))
        return True
