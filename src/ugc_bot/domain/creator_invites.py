"""Normalize staff-entered Instagram profiles and decode private bot links."""

import re
from urllib.parse import urlsplit
from uuid import UUID


def instagram_handle(value: str) -> str:
    raw = value.strip().lower()
    if "/" in raw:
        url = urlsplit(raw if "://" in raw else "https://" + raw)
        if url.scheme != "https" or url.netloc not in (
            "instagram.com",
            "www.instagram.com",
        ):
            raise ValueError("invite_instagram_invalid")
        raw = url.path.strip("/")
    else:
        raw = raw.removeprefix("@")
    if not re.fullmatch(r"[a-z0-9_.]{1,30}", raw):
        raise ValueError("invite_instagram_invalid")
    return raw


def invite_id(payload: str) -> UUID:
    if not re.fullmatch(r"oi_[0-9a-f]{32}", payload):
        raise ValueError("creator_invite_unavailable")
    return UUID(hex=payload[3:])
