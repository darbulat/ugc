"""Collect Instagram stats via ScrapeCreators into instagram_stats table.

Falls back to aiograpi when provider returns no data.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol, cast

from ugc_bot.application.delays import random_delay_seconds
from ugc_bot.application.errors import ScrapeCreatorsAPIError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramStatsProviderClient,
    InstagramStatsRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import BloggerProfile, InstagramStats
from ugc_bot.infrastructure.db.session import with_optional_tx

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


def _safe_float(value: Any) -> Optional[float]:
    """Return float from value or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any) -> Optional[bool]:
    """Return bool from value or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


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


@dataclass(frozen=True)
class AnalyticsFields:
    """Extracted analytics fields from raw Instagram response."""

    full_name: Optional[str] = None
    is_professional_account: Optional[bool] = None
    is_business_account: Optional[bool] = None
    category_name: Optional[str] = None
    external_url: Optional[str] = None
    avg_likes: Optional[float] = None
    avg_comments: Optional[float] = None
    avg_video_views: Optional[float] = None
    engagement_rate: Optional[float] = None
    posting_frequency_days: Optional[float] = None
    total_video_count: Optional[int] = None
    total_photo_count: Optional[int] = None
    video_ratio: Optional[float] = None
    followers_to_follows_ratio: Optional[float] = None
    comments_to_likes_ratio: Optional[float] = None


def _extract_profile_fields(
    user: dict,
) -> tuple[
    Optional[str],
    Optional[bool],
    Optional[bool],
    Optional[str],
    Optional[str],
]:
    """Extract profile-level fields from user dict.

    Returns (full_name, is_professional, is_business, category, external_url).
    """
    full_name = _safe_str(user.get("full_name"))
    is_professional = _safe_bool(user.get("is_professional_account"))
    is_business = _safe_bool(user.get("is_business_account"))
    category = _safe_str(user.get("category_name") or user.get("category"))
    external_url = _safe_str(user.get("external_url"))
    if not external_url:
        bio_links = user.get("bio_links")
        if isinstance(bio_links, list) and bio_links:
            first = bio_links[0]
            if isinstance(first, dict):
                external_url = _safe_str(first.get("url"))
    return full_name, is_professional, is_business, category, external_url


def _extract_post_metrics(
    posts: list[dict],
) -> tuple[
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[int],
    Optional[int],
]:
    """Compute avg engagement metrics and content counts from posts."""
    if not posts:
        return None, None, None, None, None

    total_likes = 0
    total_comments = 0
    total_video_views = 0
    video_count = 0
    photo_count = 0
    video_view_items = 0

    for post in posts:
        node = post.get("node", post) if isinstance(post, dict) else post
        if not isinstance(node, dict):
            continue

        likes = _safe_int(
            node.get("edge_liked_by", {}).get("count")
            if isinstance(node.get("edge_liked_by"), dict)
            else node.get("like_count") or node.get("likes")
        )
        comments = _safe_int(
            node.get("edge_media_to_comment", {}).get("count")
            if isinstance(node.get("edge_media_to_comment"), dict)
            else node.get("comment_count") or node.get("comments")
        )
        if likes is not None:
            total_likes += likes
        if comments is not None:
            total_comments += comments

        is_video = node.get("is_video", False)
        product_type = node.get("product_type", "")
        if is_video or product_type in ("clips", "igtv", "reels"):
            video_count += 1
            vv = _safe_int(
                node.get("video_view_count") or node.get("view_count")
            )
            if vv is not None:
                total_video_views += vv
                video_view_items += 1
        else:
            photo_count += 1

    n = len(posts)
    avg_likes = total_likes / n if n > 0 else None
    avg_comments = total_comments / n if n > 0 else None
    avg_video_views = (
        total_video_views / video_view_items if video_view_items > 0 else None
    )
    return avg_likes, avg_comments, avg_video_views, video_count, photo_count


def _extract_posting_frequency(posts: list[dict]) -> Optional[float]:
    """Compute average days between posts from timestamps."""
    timestamps: list[int] = []
    for post in posts:
        node = post.get("node", post) if isinstance(post, dict) else post
        if not isinstance(node, dict):
            continue
        ts = _safe_int(
            node.get("taken_at_timestamp")
            or node.get("taken_at")
            or node.get("timestamp")
        )
        if ts is not None:
            timestamps.append(ts)

    if len(timestamps) < 2:
        return None
    timestamps.sort(reverse=True)
    total_span = timestamps[0] - timestamps[-1]
    if total_span <= 0:
        return None
    return (total_span / (len(timestamps) - 1)) / 86400.0


def _get_posts_from_raw(raw: dict) -> list[dict]:
    """Extract post list from various API response shapes."""
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        return []

    user_val = data.get("user")
    user: dict = user_val if isinstance(user_val, dict) else data

    timeline = user.get("edge_owner_to_timeline_media")
    if isinstance(timeline, dict):
        edges = timeline.get("edges")
        if isinstance(edges, list):
            return edges

    media = user.get("media") or user.get("posts") or user.get("recent_posts")
    if isinstance(media, list):
        return media
    if isinstance(media, dict):
        items = media.get("data") or media.get("edges") or media.get("items")
        if isinstance(items, list):
            return items

    return []


def _get_user_dict(raw: dict) -> dict:
    """Get the user-level dict from various API response shapes."""
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        return {}
    user = data.get("user")
    if isinstance(user, dict):
        return user
    return data


def _extract_analytics_fields(
    raw: dict,
    followers_count: Optional[int],
    follows_count: Optional[int],
) -> AnalyticsFields:
    """Extract all analytics fields from raw Instagram API response."""
    user = _get_user_dict(raw)

    full_name, is_professional, is_business, category, external_url = (
        _extract_profile_fields(user)
    )

    posts = _get_posts_from_raw(raw)
    avg_likes, avg_comments, avg_video_views, video_count, photo_count = (
        _extract_post_metrics(posts)
    )
    posting_frequency = _extract_posting_frequency(posts)

    # Engagement rate
    engagement_rate: Optional[float] = None
    if (
        followers_count
        and followers_count > 0
        and avg_likes is not None
        and avg_comments is not None
    ):
        engagement_rate = (avg_likes + avg_comments) / followers_count

    # Video ratio
    video_ratio: Optional[float] = None
    if video_count is not None and photo_count is not None:
        total = video_count + photo_count
        if total > 0:
            video_ratio = video_count / total

    # Audience quality: followers/follows ratio
    followers_to_follows: Optional[float] = None
    if followers_count and follows_count and follows_count > 0:
        followers_to_follows = followers_count / follows_count

    # Comments to likes ratio
    comments_to_likes: Optional[float] = None
    if avg_comments is not None and avg_likes is not None and avg_likes > 0:
        comments_to_likes = avg_comments / avg_likes

    return AnalyticsFields(
        full_name=full_name,
        is_professional_account=is_professional,
        is_business_account=is_business,
        category_name=category,
        external_url=external_url,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        avg_video_views=avg_video_views,
        engagement_rate=engagement_rate,
        posting_frequency_days=posting_frequency,
        total_video_count=video_count,
        total_photo_count=photo_count,
        video_ratio=video_ratio,
        followers_to_follows_ratio=followers_to_follows,
        comments_to_likes_ratio=comments_to_likes,
    )


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
        concurrency: int = 5,
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
        self._concurrency = concurrency

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

    async def _mark_failed_attempt(
        self, profile: BloggerProfile, now: datetime
    ) -> None:
        """Bump fetched_at on failure so profile is skipped until next cycle."""

        async def _touch(session: object | None) -> None:
            await self.instagram_stats_repo.touch_fetched_at(
                profile.user_id, now, session=session
            )

        try:
            await with_optional_tx(self.transaction_manager, _touch)
        except Exception as exc:
            logger.warning(
                "Failed to mark Instagram stats failed-attempt for %s: %s",
                profile.user_id,
                exc,
            )

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
        analytics = _extract_analytics_fields(raw, followers, follows)
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
            full_name=analytics.full_name,
            is_professional_account=analytics.is_professional_account,
            is_business_account=analytics.is_business_account,
            category_name=analytics.category_name,
            external_url=analytics.external_url,
            avg_likes=analytics.avg_likes,
            avg_comments=analytics.avg_comments,
            avg_video_views=analytics.avg_video_views,
            engagement_rate=analytics.engagement_rate,
            posting_frequency_days=analytics.posting_frequency_days,
            total_video_count=analytics.total_video_count,
            total_photo_count=analytics.total_photo_count,
            video_ratio=analytics.video_ratio,
            followers_to_follows_ratio=analytics.followers_to_follows_ratio,
            comments_to_likes_ratio=analytics.comments_to_likes_ratio,
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

        sem = asyncio.Semaphore(self._concurrency)

        async def _process_limited(
            profile: BloggerProfile,
        ) -> tuple[bool, dict]:
            async with sem:
                try:
                    result = await self._process_one_profile(profile, now)
                except Exception as exc:
                    logger.warning(
                        "Unexpected error processing profile %s: %s",
                        profile.user_id,
                        exc,
                    )
                    result = (
                        False,
                        {
                            "user_id": str(profile.user_id),
                            "username": _username_from_profile(profile) or "",
                            "reason": str(exc),
                        },
                    )
                if not result[0]:
                    await self._mark_failed_attempt(profile, now)
                await asyncio.sleep(random_delay_seconds(self._delay_seconds))
                return result

        results = await asyncio.gather(*[_process_limited(p) for p in profiles])

        updated = 0
        errors = 0
        updated_users: list[dict] = []
        failed_users: list[dict] = []
        for success, user_info in results:
            if success:
                updated += 1
                updated_users.append(user_info)
            else:
                errors += 1
                failed_users.append(user_info)

        return RunOnceResult(
            updated=updated,
            errors=errors,
            updated_users=updated_users,
            failed_users=failed_users,
        )
