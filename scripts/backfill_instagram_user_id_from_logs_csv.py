#!/usr/bin/env python3
"""Fill instagram_user_id in blogger_profiles from logs CSV.

CSV must have columns: Date, sender_id, user_id.
- sender_id is instagram_user_id (from Instagram webhook logs).
- user_id is the app user UUID.

For each row: load blogger profile by user_id, set instagram_user_id=sender_id,
save. Skips if no profile or user_id invalid.
"""

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path
from uuid import UUID

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.entities import BloggerProfile
from ugc_bot.infrastructure.db.session import create_session_factory

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_logs_csv(path: Path) -> list[tuple[UUID, str]]:
    """Read CSV with Date, sender_id, user_id. Returns (user_id, sender_id)."""
    rows: list[tuple[UUID, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid_str = (row.get("user_id") or "").strip()
            sender = (row.get("sender_id") or "").strip()
            if not uid_str or not sender:
                continue
            try:
                uid = UUID(uid_str)
            except ValueError:
                logger.warning("Invalid user_id in CSV: %s", uid_str)
                continue
            rows.append((uid, sender))
    return rows


def profile_with_instagram_user_id(
    profile: BloggerProfile, instagram_user_id: str
) -> BloggerProfile:
    """Return copy of profile with instagram_user_id set."""
    return BloggerProfile(
        user_id=profile.user_id,
        instagram_url=profile.instagram_url,
        confirmed=profile.confirmed,
        city=profile.city,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
        barter=profile.barter,
        work_format=profile.work_format,
        updated_at=profile.updated_at,
        wanted_to_change_terms_count=profile.wanted_to_change_terms_count,
        blogger_gender=profile.blogger_gender,
        instagram_user_id=instagram_user_id,
        instagram_followers_count=profile.instagram_followers_count,
        instagram_media_count=profile.instagram_media_count,
        instagram_follows_count=profile.instagram_follows_count,
        instagram_biography=profile.instagram_biography,
        instagram_username=profile.instagram_username,
        instagram_stats_fetched_at=profile.instagram_stats_fetched_at,
    )


async def run(csv_path: Path, dry_run: bool) -> int:
    """Read CSV and set instagram_user_id on blogger profiles."""
    config = load_config()
    if not config.db.database_url:
        logger.error("DATABASE_URL is required.")
        return 1

    records = load_logs_csv(csv_path)
    if not records:
        logger.error("No valid rows in CSV (need user_id, sender_id).")
        return 1

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    repos = repository_factory.build_repos(session_factory)
    blogger_repo = repos["blogger_repo"]

    updated = 0
    skipped_no_profile = 0
    skipped_unchanged = 0

    for user_id, sender_id in records:
        async with session_factory() as session:
            profile = await blogger_repo.get_by_user_id(
                user_id, session=session
            )
        if profile is None:
            logger.debug("No blogger profile for user_id=%s", user_id)
            skipped_no_profile += 1
            continue
        if profile.instagram_user_id == sender_id:
            skipped_unchanged += 1
            continue
        if dry_run:
            logger.info(
                "Would set user_id=%s instagram_user_id=%s",
                user_id,
                sender_id,
            )
            updated += 1
            continue
        updated_profile = profile_with_instagram_user_id(profile, sender_id)
        async with session_factory() as session:
            await blogger_repo.save(updated_profile, session=session)
            await session.commit()
        updated += 1
        logger.info(
            "Set user_id=%s instagram_user_id=%s",
            user_id,
            sender_id,
        )

    logger.info(
        "Done. updated=%s skipped_no_profile=%s skipped_unchanged=%s "
        "dry_run=%s",
        updated,
        skipped_no_profile,
        skipped_unchanged,
        dry_run,
    )
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Set instagram_user_id on blogger profiles from logs CSV. "
            "CSV columns: Date, sender_id, user_id."
        ),
    )
    parser.add_argument(
        "csv",
        type=Path,
        metavar="FILE",
        help="CSV file with Date, sender_id, user_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only log what would be updated, do not write to DB.",
    )
    args = parser.parse_args()
    if not args.csv.exists():
        logger.error("File not found: %s", args.csv)
        return 1
    return asyncio.run(run(csv_path=args.csv, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
