"""Canonical creator social links and observed, never estimated, metrics."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from ugc_bot.domain.enums import WorkFormat


class SocialPlatform(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    TELEGRAM = "telegram"
    VK = "vk"


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
}
_CANONICAL_HOST = {
    SocialPlatform.INSTAGRAM: "www.instagram.com",
    SocialPlatform.TIKTOK: "www.tiktok.com",
    SocialPlatform.YOUTUBE: "www.youtube.com",
    SocialPlatform.TELEGRAM: "t.me",
    SocialPlatform.VK: "vk.com",
}


def normalize_social_url(
    platform: SocialPlatform,
    url: str,
) -> tuple[str, str]:
    """Accept public account URLs only, with an exact platform host."""
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _HOSTS[platform]
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
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
    else:
        handle = _single_handle(platform, path)
        path = handle
    return f"https://{_CANONICAL_HOST[platform]}/{path}", handle


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
