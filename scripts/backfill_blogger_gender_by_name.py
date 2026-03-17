#!/usr/bin/env python3
"""Backfill blogger_gender for bloggers with NULL gender based on display name.

Iterates over blogger_profiles with blogger_gender IS NULL, takes the first
word from User.username (display name), infers gender from name lists, and
updates the profile when the name is unambiguous. Logs a warning and skips
for ambiguous or unknown names.

Name lists are loaded from scripts/data/male_names.txt, female_names.txt,
ambiguous_names.txt if present (see scripts/build_name_data.py); otherwise
uses a small built-in fallback. Optional --use-api queries genderize.io
for names not in the dictionary (rate-limited, free tier ~100/day).
"""

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.enums import BloggerGender
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)

# Fallback if data files are missing (small set)
_DEFAULT_MALE: frozenset[str] = frozenset({
    "александр", "алексей", "андрей", "дмитрий", "иван", "сергей", "михаил",
    "alexander", "john", "michael", "dmitry", "ivan", "pavel",
})
_DEFAULT_FEMALE: frozenset[str] = frozenset({
    "александра", "анна", "мария", "елена", "ольга", "наталья", "ирина",
    "anna", "maria", "elena", "olga", "natalia",
})
_DEFAULT_AMBIGUOUS: frozenset[str] = frozenset({
    "саша", "женя", "валя", "слава", "шура", "sasha", "zhenya", "valya",
})


def _load_names_from_file(path: Path) -> frozenset[str]:
    """Load lowercase names, one per line, skip empty."""
    if not path.exists():
        return frozenset()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip().lower()
        if s and any(c.isalpha() for c in s):
            names.add(s)
    return frozenset(names)


_NAME_SETS_CACHE: tuple[frozenset[str], frozenset[str], frozenset[str]] | None = None


def _get_name_sets() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return (MALE_NAMES, FEMALE_NAMES, AMBIGUOUS_NAMES) from data dir or defaults."""
    global _NAME_SETS_CACHE  # noqa: PLW0603
    if _NAME_SETS_CACHE is not None:
        return _NAME_SETS_CACHE
    data_dir = Path(__file__).resolve().parent / "data"
    male = _load_names_from_file(data_dir / "male_names.txt")
    female = _load_names_from_file(data_dir / "female_names.txt")
    ambiguous = _load_names_from_file(data_dir / "ambiguous_names.txt")
    if not male:
        male = _DEFAULT_MALE
    if not female:
        female = _DEFAULT_FEMALE
    if not ambiguous:
        ambiguous = _DEFAULT_AMBIGUOUS
    _NAME_SETS_CACHE = (male, female, ambiguous)
    return _NAME_SETS_CACHE

# Split username by spaces, underscores, digits, or common separators to get first token.
_FIRST_WORD_RE = re.compile(r"^[^a-zA-Zа-яА-ЯёЁ]*([a-zA-Zа-яА-ЯёЁ]+)")


def extract_first_name(username: str) -> str:
    """Extract the first word (name-like token) from username.

    Uses the first sequence of letters (Latin or Cyrillic). Returns empty
    string if no letters found.
    """
    if not username or not username.strip():
        return ""
    match = _FIRST_WORD_RE.search(username.strip())
    if not match:
        return ""
    return match.group(1).strip()


def infer_gender(first_name: str) -> tuple[BloggerGender | None, str | None]:
    """Infer gender from first name using name lists.

    Returns (gender, None) when the name is unambiguous (MALE or FEMALE).
    Returns (None, 'ambiguous') for ambiguous names (e.g. Саша, Женя).
    Returns (None, 'unknown') when the name is empty, has no letters, or
    is not in any list.
    """
    if not first_name:
        return (None, "unknown")
    key = first_name.strip().lower()
    if not key or not any(c.isalpha() for c in key):
        return (None, "unknown")
    male, female, ambiguous = _get_name_sets()
    if key in ambiguous:
        return (None, "ambiguous")
    if key in male:
        return (BloggerGender.MALE, None)
    if key in female:
        return (BloggerGender.FEMALE, None)
    return (None, "unknown")


async def _infer_gender_via_api(first_name: str) -> BloggerGender | None:
    """Query genderize.io for name. Returns MALE/FEMALE or None. Rate-limited."""
    try:
        import httpx
    except ImportError:
        return None
    key = first_name.strip().lower()
    if not key or len(key) < 2:
        return None
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(
                "https://api.genderize.io",
                params={"name": key},
            )
            r.raise_for_status()
            data = r.json()
            gender = data.get("gender")
            prob = data.get("probability", 0.0)
            if gender == "male" and prob >= 0.85:
                return BloggerGender.MALE
            if gender == "female" and prob >= 0.85:
                return BloggerGender.FEMALE
    except Exception:  # noqa: BLE001
        pass
    return None


async def run(dry_run: bool, use_api: bool = False) -> int:
    """Backfill blogger_gender for profiles with NULL gender based on username."""
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    repos = repository_factory.build_repos(session_factory)
    blogger_repo = repos["blogger_repo"]

    async with session_factory() as session:
        result = await session.execute(
            select(BloggerProfileModel.user_id, UserModel.username)
            .select_from(BloggerProfileModel)
            .join(UserModel, BloggerProfileModel.user_id == UserModel.user_id)
            .where(BloggerProfileModel.blogger_gender.is_(None))
        )
        rows = list(result.all())

    if not rows:
        print("No bloggers with empty blogger_gender.")
        return 0

    updated_count = 0
    skipped_ambiguous = 0
    skipped_unknown = 0

    for user_id, username in rows:
        username_str = username or ""
        first_name = extract_first_name(username_str)
        gender, skip_reason = infer_gender(first_name)

        if gender is None and skip_reason == "unknown" and use_api:
            gender = await _infer_gender_via_api(first_name)
            if gender is not None:
                skip_reason = None
            await asyncio.sleep(1.0)  # rate limit for genderize.io free tier

        if skip_reason == "ambiguous":
            skipped_ambiguous += 1
            logger.warning(
                "Gender not recognized (ambiguous name), skipping: user_id=%s name=%s",
                user_id,
                first_name or username_str or "(empty)",
            )
            continue
        if skip_reason == "unknown":
            skipped_unknown += 1
            logger.warning(
                "Gender not recognized (unknown name), skipping: user_id=%s name=%s",
                user_id,
                first_name or username_str or "(empty)",
            )
            continue

        assert gender is not None
        if dry_run:
            updated_count += 1
            logger.info(
                "Would set blogger_gender=%s for user_id=%s (name=%s)",
                gender.value,
                user_id,
                first_name,
            )
            continue

        async with session_factory() as session:
            profile = await blogger_repo.get_by_user_id(
                user_id,
                session=session,
            )
            if profile is None:
                logger.warning("Blogger profile not found for user_id=%s", user_id)
                continue
            updated = replace(profile, blogger_gender=gender)
            await blogger_repo.save(updated, session=session)
            await session.commit()
            updated_count += 1
            logger.info(
                "Set blogger_gender=%s for user_id=%s (name=%s)",
                gender.value,
                user_id,
                first_name,
            )

    print(
        f"Processed {len(rows)}: updated={updated_count}, "
        f"skipped_ambiguous={skipped_ambiguous}, skipped_unknown={skipped_unknown} "
        f"(dry_run={dry_run})"
    )
    if dry_run and updated_count > 0:
        print("Run without --dry-run to apply changes.")
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Set blogger_gender for bloggers with NULL gender based on "
            "the first word of their display name (User.username). "
            "Skips and logs a warning for ambiguous or unknown names."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be updated, do not change the database.",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="For unknown names, query genderize.io (rate-limited, free ~100/day).",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run, use_api=args.use_api))


if __name__ == "__main__":
    sys.exit(main())
