"""Collect Instagram stats via ScrapeCreators into instagram_stats table.

Falls back to aiograpi when provider returns no data.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol, cast

from ugc_bot.application.errors import ScrapeCreatorsAPIError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramStatsProviderClient,
    InstagramStatsRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerProfile, InstagramStats
from ugc_bot.infrastructure.db.session import with_optional_tx
from ugc_bot.infrastructure.instagram.delays import random_delay_seconds

logger = logging.getLogger(__name__)


class AiograpiStatsFetcherProtocol(Protocol):
    """Protocol for aiograpi fallback fetcher."""

    async def get_profile_stats_by_username(
        self, username: str
    ) -> Optional[dict[str, Any]]:
        """Return raw stats dict or None."""
        ...  # pragma: no cover


@dataclass
class RunOnceResult:
    """Result of a single Instagram stats collection cycle."""

    updated: int
    errors: int
    updated_users: list[dict]
    failed_users: list[dict]


def _safe_int(value: Any) -> Optional[int]:
    """Return int from value or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any) -> Optional[str]:
    """Return non-empty string or None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _extract_from_counts(
    counts: dict,
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Extract followers, follows, media from counts sub-dict."""
    followers = _safe_int(
        counts.get("followed_by")
        or counts.get("follower_count")
        or counts.get("followers")
    )
    follows = _safe_int(counts.get("follows"))
    media = _safe_int(counts.get("media"))
    return (followers, follows, media)


def _username_from_url(url_val: Any) -> Optional[str]:
    """Extract username from Instagram profile URL if present."""
    if not url_val or not isinstance(url_val, str):
        return None
    s = url_val.strip().rstrip("/")
    if "/" in s:
        return s.rsplit("/", 1)[-1].split("?")[0].strip() or None
    return s.split("?")[0].strip() or None


def _extract_from_data(
    data: dict,
) -> tuple[
    Optional[int], Optional[int], Optional[int], Optional[str], Optional[str]
]:
    """Extract counts and profile fields from data dict (no nested counts).

    Supports instagram-v2 style (followers_count, username, biography) and
    instagram-statistics-api style (usersCount, screenName, description).
    """
    followers = _safe_int(
        data.get("followers_count")
        or data.get("follower_count")
        or data.get("followers")
        or data.get("usersCount")
    )
    follows = _safe_int(data.get("follows_count") or data.get("follows"))
    media = _safe_int(
        data.get("media_count")
        or data.get("media")
        or data.get("postsCount")
        or data.get("totalPosts")
        or data.get("mediaCount")
        or data.get("posts_count")
    )
    username = _safe_str(
        data.get("username") or data.get("screenName")
    ) or _username_from_url(data.get("url"))
    biography = _safe_str(
        data.get("biography") or data.get("bio") or data.get("description")
    )
    return (followers, follows, media, username, biography)


def _extract_from_web_user(
    user: dict,
) -> tuple[
    Optional[int], Optional[int], Optional[int], Optional[str], Optional[str]
]:
    """Extract from Instagram web_profile_info data.user (edge_* counts)."""
    followers = _safe_int(
        user.get("edge_followed_by", {}).get("count")
        if isinstance(user.get("edge_followed_by"), dict)
        else None
    )
    follows = _safe_int(
        user.get("edge_follow", {}).get("count")
        if isinstance(user.get("edge_follow"), dict)
        else None
    )
    media = _safe_int(
        user.get("edge_owner_to_timeline_media", {}).get("count")
        if isinstance(user.get("edge_owner_to_timeline_media"), dict)
        else None
    )
    username = _safe_str(user.get("username"))
    biography = _safe_str(user.get("biography"))
    return (followers, follows, media, username, biography)


def _extract_typed_fields(
    raw: dict,
) -> tuple[
    Optional[int], Optional[int], Optional[int], Optional[str], Optional[str]
]:
    """Extract typed fields from raw API response.

    Tries common API shapes (e.g. data.counts.*, top-level).
    """
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    counts = None
    if data and isinstance(data, dict):
        counts = (
            data.get("counts") if isinstance(data.get("counts"), dict) else None
        )

    if isinstance(counts, dict):
        followers, follows, media = _extract_from_counts(counts)
        username = (
            _safe_str(data.get("username") or data.get("screenName"))
            if data
            else None
        )
        if not username and data:
            username = _username_from_url(data.get("url"))
        biography = _safe_str(
            (
                data.get("biography")
                or data.get("bio")
                or data.get("description")
            )
            if data
            else None
        )
    elif isinstance(data, dict) and isinstance(data.get("user"), dict):
        followers, follows, media, username, biography = _extract_from_web_user(
            data["user"]
        )
    elif isinstance(data, dict):
        followers, follows, media, username, biography = _extract_from_data(
            data
        )
    else:  # pragma: no cover - defensive when data is not a dict
        followers, follows, media = None, None, None
        username = (
            _safe_str(raw.get("username")) if isinstance(raw, dict) else None
        )
        biography = _safe_str(
            raw.get("biography") or raw.get("bio")
            if isinstance(raw, dict)
            else None
        )

    if username is None and isinstance(raw, dict):
        username = _safe_str(raw.get("username"))
    if biography is None and isinstance(raw, dict):
        biography = _safe_str(raw.get("biography") or raw.get("bio"))

    return (followers, follows, media, username, biography)


def _extract_instagram_id(raw: dict) -> Optional[str]:
    """Extract Instagram user id from raw API response.

    Tries data.user.id (ScrapeCreators/web), then data.id, then top-level id.
    """
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if isinstance(data, dict):
        user = data.get("user")
        if isinstance(user, dict):
            uid = user.get("id")
            if uid is not None:
                s = str(uid).strip()
                if s:
                    return s
        uid = data.get("id")
        if uid is not None:
            s = str(uid).strip()
            if s:
                return s
    uid = raw.get("id")
    if uid is not None:
        s = str(uid).strip()
        if s:
            return s
    return None  # pragma: no cover - defensive fallback


def _username_from_profile(profile: BloggerProfile) -> Optional[str]:
    """Get Instagram username from profile (username or parsed from URL)."""
    if profile.instagram_username and profile.instagram_username.strip():
        return profile.instagram_username.strip()
    url = (profile.instagram_url or "").strip().rstrip("/")
    if not url:
        return None
    if "/" in url:
        return url.rsplit("/", 1)[-1].split("?")[0].strip() or None
    return url.split("?")[0].strip() or None


class InstagramStatsCollectorService:
    """Collect Instagram stats via ScrapeCreators into instagram_stats table.

    Falls back to aiograpi when provider returns no data.
    """

    def __init__(
        self,
        blogger_repo: BloggerProfileRepository,
        instagram_stats_repo: InstagramStatsRepository,
        stats_provider_client: Optional[InstagramStatsProviderClient] = None,
        transaction_manager: Optional[TransactionManager] = None,
        batch_size: int = 50,
        delay_seconds: float = 1.0,
        stats_update_interval_seconds: int = 86400,
        aiograpi_fetcher: Optional[AiograpiStatsFetcherProtocol] = None,
    ) -> None:
        """Initialize the service.

        Args:
            blogger_repo: Repository for blogger profiles.
            instagram_stats_repo: Repository for instagram_stats.
            stats_provider_client: Client that returns stats with provider id.
            transaction_manager: Optional transaction manager for saves.
            batch_size: Max profiles to process per run.
            delay_seconds: Delay between API requests to respect rate limits.
            stats_update_interval_seconds: (Re)fetch only if no instagram_stats
                row or fetched_at is older than this many seconds.
            aiograpi_fetcher: Optional fallback when primary provider
                returns no data.
        """
        self.blogger_repo = blogger_repo
        self.instagram_stats_repo = instagram_stats_repo
        self.stats_provider_client = stats_provider_client
        self.transaction_manager = transaction_manager
        self._batch_size = batch_size
        self._delay_seconds = delay_seconds
        self._stats_update_interval_seconds = stats_update_interval_seconds
        self._aiograpi_fetcher = aiograpi_fetcher

    async def _fetch_raw_stats(
        self, username: str, user_id_str: str
    ) -> tuple[Optional[dict], str, Optional[str]]:
        """Fetch raw stats from primary client, optionally fallback to aiograpi.

        Returns (raw_dict, provider_name, error_reason). On success raw_dict is
        set and error_reason is None. On failure raw_dict is None and
        error_reason is set for failed_users.
        """
        provider = "scrapecreators"
        error_reason: Optional[str] = None
        client = cast(
            InstagramStatsProviderClient,
            self.stats_provider_client,
        )
        try:
            raw, provider = await client.get_profile_stats_with_provider(
                username
            )
        except ScrapeCreatorsAPIError as exc:
            if exc.status_code >= 500:
                logger.warning(
                    "ScrapeCreators 5xx (transient), will try fallback",
                    extra={
                        "user_id": user_id_str,
                        "username": username,
                        "status_code": exc.status_code,
                    },
                )
                error_reason = f"ScrapeCreators API error: {exc.status_code}"
                raw, provider = None, ""
            else:
                raise
        except Exception as exc:
            logger.warning(
                "Failed to fetch Instagram stats",
                extra={
                    "user_id": user_id_str,
                    "username": username,
                    "error": str(exc),
                },
                exc_info=exc,
            )
            return None, "", str(exc)

        if raw and isinstance(raw, dict):
            return raw, provider or "scrapecreators", None

        if self._aiograpi_fetcher:
            try:
                raw = (
                    await self._aiograpi_fetcher.get_profile_stats_by_username(
                        username
                    )
                )
                if raw and isinstance(raw, dict):
                    return raw, "aiograpi", None
            except Exception as exc:
                logger.warning(
                    "Aiograpi fallback failed for %s: %s",
                    username,
                    exc,
                    extra={
                        "user_id": user_id_str,
                        "username": username,
                        "error": str(exc),
                    },
                )
                return None, "", str(exc)

        return None, "", error_reason or "no_stats_data"

    async def _process_one_profile(
        self, profile: BloggerProfile, now: datetime
    ) -> tuple[bool, dict]:
        """Process one profile: fetch stats and save. Return (ok, user_info)."""
        user_id_str = str(profile.user_id)
        username = _username_from_profile(profile)
        if not username:
            logger.debug(
                "Skipping profile without Instagram username",
                extra={"user_id": user_id_str},
            )
            return False, {
                "user_id": user_id_str,
                "username": "",
                "reason": "no_instagram_username",
            }

        raw, _provider, error_reason = await self._fetch_raw_stats(
            username, user_id_str
        )
        if not raw or not isinstance(raw, dict):
            return False, {
                "user_id": user_id_str,
                "username": username,
                "reason": error_reason or "no_stats_data",
            }

        followers, follows, media, parsed_username, biography = (
            _extract_typed_fields(raw)
        )
        stats = InstagramStats(
            user_id=profile.user_id,
            raw_response=raw,
            fetched_at=now,
            followers_count=followers,
            follows_count=follows,
            media_count=media,
            instagram_username=parsed_username or username,
            biography=biography,
            provider=_provider or "scrapecreators",
            instagram_id=_extract_instagram_id(raw),
        )

        async def _save(
            session: object | None,
            stats_to_save: InstagramStats = stats,
        ) -> None:
            await self.instagram_stats_repo.save(stats_to_save, session=session)

        await with_optional_tx(self.transaction_manager, _save)
        logger.debug(
            "Saved Instagram stats",
            extra={
                "user_id": user_id_str,
                "username": username,
                "followers": followers,
            },
        )
        return True, {"user_id": user_id_str, "username": username}

    async def run_once(self) -> RunOnceResult:
        """Fetch stats for one batch; save to instagram_stats.

        Returns:
            RunOnceResult with updated/error counts and user lists.
        """
        if not self.stats_provider_client:
            logger.warning(
                "Stats provider client not configured, skipping stats update"
            )
            return RunOnceResult(
                updated=0, errors=0, updated_users=[], failed_users=[]
            )

        now = datetime.now(timezone.utc)
        threshold = now - timedelta(seconds=self._stats_update_interval_seconds)

        async def _list(session: object | None):
            return await self.blogger_repo.list_confirmed_with_instagram_id(
                limit=self._batch_size,
                offset=0,
                stats_older_than=threshold,
                session=session,
            )

        profiles = await with_optional_tx(self.transaction_manager, _list)
        if not profiles:
            logger.debug(
                "No confirmed profiles with instagram_user_id to update"
            )
            return RunOnceResult(
                updated=0, errors=0, updated_users=[], failed_users=[]
            )

        updated = 0
        errors = 0
        updated_users: list[dict] = []
        failed_users: list[dict] = []

        for profile in profiles:
            success, user_info = await self._process_one_profile(profile, now)
            if success:
                updated += 1
                updated_users.append(user_info)
            else:
                errors += 1
                failed_users.append(user_info)
            await asyncio.sleep(random_delay_seconds(self._delay_seconds))

        return RunOnceResult(
            updated=updated,
            errors=errors,
            updated_users=updated_users,
            failed_users=failed_users,
        )
