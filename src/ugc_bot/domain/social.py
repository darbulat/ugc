"""Canonical creator social links and observed, never estimated, metrics."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

from ugc_bot.domain.enums import WorkFormat


class SocialPlatform(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    TELEGRAM = "telegram"
    VK = "vk"
    DZEN = "dzen"
    RUTUBE = "rutube"
    OTHER = "other"


ORDER_TARGET_PLATFORMS = frozenset(
    {
        SocialPlatform.INSTAGRAM,
        SocialPlatform.TIKTOK,
        SocialPlatform.YOUTUBE,
        SocialPlatform.TELEGRAM,
        SocialPlatform.VK,
    }
)

SOCIAL_PLATFORM_LABELS = {
    SocialPlatform.INSTAGRAM: "Instagram",
    SocialPlatform.TIKTOK: "TikTok",
    SocialPlatform.YOUTUBE: "YouTube",
    SocialPlatform.TELEGRAM: "Telegram",
    SocialPlatform.VK: "VK",
    SocialPlatform.DZEN: "Дзен",
    SocialPlatform.RUTUBE: "Rutube",
}


class CreatorIdentityConflict(ValueError):
    """A verified Instagram identity already belongs to another creator."""


@dataclass(frozen=True, slots=True)
class SocialAccount:
    account_id: UUID
    user_id: UUID
    platform: SocialPlatform
    url: str
    handle: str
    verified: bool
    work_format: WorkFormat
    created_at: datetime
    updated_at: datetime
    external_id: str | None = None
    followers_count: int | None = None
    metrics_source: str | None = None
    metrics_fetched_at: datetime | None = None
    verified_at: datetime | None = None
    verification_observed_at: datetime | None = None
    verification_source: str | None = None


_HOSTS = {
    SocialPlatform.INSTAGRAM: {"instagram.com", "www.instagram.com"},
    SocialPlatform.TIKTOK: {"tiktok.com", "www.tiktok.com", "m.tiktok.com"},
    SocialPlatform.YOUTUBE: {"youtube.com", "www.youtube.com", "m.youtube.com"},
    SocialPlatform.TELEGRAM: {"t.me", "telegram.me", "www.t.me"},
    SocialPlatform.VK: {"vk.com", "www.vk.com", "m.vk.com"},
    SocialPlatform.DZEN: {"dzen.ru", "www.dzen.ru"},
    SocialPlatform.RUTUBE: {"rutube.ru", "www.rutube.ru"},
}
_CANONICAL_HOST = {
    SocialPlatform.INSTAGRAM: "www.instagram.com",
    SocialPlatform.TIKTOK: "www.tiktok.com",
    SocialPlatform.YOUTUBE: "www.youtube.com",
    SocialPlatform.TELEGRAM: "t.me",
    SocialPlatform.VK: "vk.com",
    SocialPlatform.DZEN: "dzen.ru",
    SocialPlatform.RUTUBE: "rutube.ru",
}


def normalize_social_url(
    platform: SocialPlatform,
    url: str,
    *,
    platform_name: str | None = None,
) -> tuple[str, str]:
    """Normalize profile links and retain the name of an Other platform."""
    parsed = _parse_https_profile_url(url)
    host = parsed.hostname or ""
    if platform == SocialPlatform.OTHER:
        return _other_profile(parsed, host, platform_name)
    if host not in _HOSTS[platform]:
        raise ValueError(
            "A public HTTPS profile URL on this platform is required"
        )
    path = parsed.path.strip("/")
    parts = path.split("/")
    if platform == SocialPlatform.YOUTUBE:
        handle, path = _youtube_path(parts)
    elif platform == SocialPlatform.TIKTOK:
        if not re.fullmatch(r"@[A-Za-z0-9._]{1,24}", path):
            raise ValueError("A TikTok account URL is required")
        handle = path[1:].lower()
        path = "@" + handle
    elif platform == SocialPlatform.DZEN:
        handle = _dzen_handle(path)
    elif platform == SocialPlatform.RUTUBE:
        if not re.fullmatch(r"(?:channel|u)/[\w.-]{1,100}", path):
            raise ValueError("A Rutube channel URL is required")
        handle = parts[1]
    else:
        handle = _single_handle(platform, path)
        path = handle
    return f"https://{_CANONICAL_HOST[platform]}/{path}", handle


def _parse_https_profile_url(url: str) -> SplitResult:
    cleaned = url.strip()
    if len(cleaned) > 2048 or any(
        c.isspace() or c == "\\" or ord(c) < 32 for c in cleaned
    ):
        raise ValueError("Invalid social URL")
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ValueError("A public HTTPS profile URL is required")
    return parsed


def _other_profile(
    parsed: SplitResult, host: str, platform_name: str | None
) -> tuple[str, str]:
    name = " ".join((platform_name or "").split())
    if not 1 <= len(name) <= 100 or not re.fullmatch(
        r"[\w.-]+\.[a-zA-Z\u0080-\uffff][\w-]*", host
    ):
        raise ValueError("A platform name and HTTPS URL are required")
    return urlunsplit(("https", host, parsed.path, parsed.query, "")), name


def _dzen_handle(path: str) -> str:
    if re.fullmatch(r"id/[A-Fa-f0-9]{24}", path):
        handle = path.split("/")[1]
    elif re.fullmatch(r"[\w.-]{1,100}", path) and path.lower() not in {
        "a",
        "b",
        "id",
        "video",
        "shorts",
        "article",
        "media",
        "search",
        "news",
    }:
        handle = path
    else:
        raise ValueError("A Dzen channel URL is required")
    return handle


def _youtube_path(parts: list[str]) -> tuple[str, str]:
    if len(parts) == 1 and re.fullmatch(r"@[\w.-]{1,100}", parts[0]):
        handle = parts[0][1:].lower()
        return handle, "@" + handle
    if (
        len(parts) == 2
        and parts[0] in {"channel", "c", "user"}
        and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", parts[1])
    ):
        handle = parts[1] if parts[0] == "channel" else parts[1].lower()
        return handle, parts[0] + "/" + handle
    raise ValueError("A YouTube channel URL is required")


def _single_handle(platform: SocialPlatform, path: str) -> str:
    pattern = r"[A-Za-z0-9_.]{1,100}"
    reserved: set[str] = set()
    if platform == SocialPlatform.INSTAGRAM:
        pattern = r"[A-Za-z0-9_.]{1,30}"
        reserved = {"p", "reel", "reels", "stories", "explore", "accounts"}
    elif platform == SocialPlatform.TELEGRAM:
        pattern = r"[A-Za-z][A-Za-z0-9_]{3,31}"
        reserved = {"share", "proxy", "socks", "joinchat", "addstickers"}
    elif platform == SocialPlatform.VK:
        reserved = {"feed", "wall", "video", "clip", "photo", "albums"}
        if re.match(r"(?:wall|video|clip|photo)-?\d", path):
            raise ValueError("A VK account URL is required")
    if not re.fullmatch(pattern, path) or path.lower() in reserved:
        raise ValueError("A public account URL is required")
    return path.lower()
