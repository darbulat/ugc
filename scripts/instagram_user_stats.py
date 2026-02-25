#!/usr/bin/env python3
"""Get Instagram user statistics by username using aiograpi.

Requires INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables
(or .env file) for API login. Session is saved to avoid repeated logins.

Usage:
    INSTAGRAM_USERNAME=... INSTAGRAM_PASSWORD=... python scripts/instagram_user_stats.py TARGET_USERNAME
    python scripts/instagram_user_stats.py TARGET_USERNAME --json

Session file .instagram_session.json is in project root and ignored by git.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SESSION_FILE = Path(__file__).resolve().parents[1] / ".instagram_session.json"


def load_dotenv_if_available() -> None:
    """Load .env from project root if python-dotenv is installed."""
    try:
        import dotenv

        root = Path(__file__).resolve().parents[1]
        env_path = root / ".env"
        if env_path.exists():
            dotenv.load_dotenv(env_path)
    except ImportError:
        pass


async def _fetch_user_async(
    username: str,
    instagram_username: str,
    instagram_password: str,
    session_path: Path,
) -> dict:
    """Login (reuse or create session), fetch user, persist session. Returns stats dict."""
    from aiograpi import Client
    from aiograpi.exceptions import LoginRequired, UserNotFound

    cl = Client()
    if session_path.exists():
        try:
            cl.load_settings(str(session_path))
            logger.debug("Loaded session from %s", session_path)
        except Exception as e:
            logger.warning("Could not load session: %s", e)

    try:
        await cl.login(instagram_username, instagram_password)
    except Exception as e:
        raise RuntimeError(f"Instagram login failed: {e}") from e

    try:
        user = await cl.user_info_by_username_v1(username)
    except UserNotFound as e:
        raise RuntimeError(f"User '{username}' not found") from e
    except LoginRequired as e:
        logger.info("Session expired, re-logging in...")
        cl = Client()
        try:
            await cl.login(instagram_username, instagram_password)
            user = await cl.user_info_by_username_v1(username)
        except Exception as e2:
            raise RuntimeError(f"Re-login or fetch failed: {e2}") from e2
        cl.dump_settings(str(session_path))
        logger.info("Session saved to %s", session_path)
    else:
        try:
            cl.dump_settings(str(session_path))
        except OSError as e:
            logger.warning("Could not save session: %s", e)

    return {
        "username": user.username,
        "full_name": user.full_name,
        "pk": user.pk,
        "is_private": user.is_private,
        "is_verified": user.is_verified,
        "is_business": user.is_business,
        "follower_count": user.follower_count,
        "following_count": user.following_count,
        "media_count": user.media_count,
        "biography": user.biography or "",
        "external_url": str(user.external_url) if user.external_url else None,
        "profile_pic_url": str(user.profile_pic_url) if user.profile_pic_url else None,
    }


def get_user_stats(
    username: str,
    instagram_username: str,
    instagram_password: str,
    session_path: Path | None = None,
) -> dict:
    """Fetch Instagram user info and return statistics dict.

    Uses saved session when possible to avoid repeated logins. Session is stored
    at session_path (default: project root .instagram_session.json).

    Args:
        username: Target Instagram username to look up.
        instagram_username: Instagram account username for API login.
        instagram_password: Instagram account password for API login.
        session_path: Path to session file. Defaults to .instagram_session.json in project root.

    Returns:
        Dict with user statistics (followers, following, media_count, etc.).

    Raises:
        RuntimeError: On login or user fetch failure.
    """
    path = session_path or DEFAULT_SESSION_FILE
    return asyncio.run(
        _fetch_user_async(
            username, instagram_username, instagram_password, path
        )
    )


def main() -> int:
    """Entry point: parse args, load env, fetch and print stats."""
    load_dotenv_if_available()

    parser = argparse.ArgumentParser(
        description="Get Instagram user statistics by username (aiograpi)."
    )
    parser.add_argument(
        "username",
        help="Instagram username to fetch statistics for",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Path to session file (default: .instagram_session.json in project root)",
    )
    args = parser.parse_args()

    instagram_username = os.environ.get("INSTAGRAM_USERNAME", "").strip()
    instagram_password = os.environ.get("INSTAGRAM_PASSWORD", "").strip()
    if not instagram_username or not instagram_password:
        logger.error(
            "Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD (env or .env)"
        )
        return 1

    try:
        stats = get_user_stats(
            args.username,
            instagram_username,
            instagram_password,
            session_path=args.session,
        )
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    print(f"@{stats['username']} ({stats['full_name']})")
    print(f"  Followers: {stats['follower_count']:,}")
    print(f"  Following: {stats['following_count']:,}")
    print(f"  Posts: {stats['media_count']:,}")
    print(f"  Private: {stats['is_private']}  Verified: {stats['is_verified']}")
    if stats["biography"]:
        print(f"  Bio: {stats['biography'][:200]}")
    if stats["external_url"]:
        print(f"  Link: {stats['external_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
