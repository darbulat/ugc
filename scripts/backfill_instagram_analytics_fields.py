#!/usr/bin/env python3
"""Backfill analytics fields in instagram_stats from existing raw_response.

Iterates over instagram_stats rows where analytics fields are NULL,
re-runs the analytics extraction logic on the stored raw_response JSON,
and writes the results back to the database.

Usage:
    uv run python scripts/backfill_instagram_analytics_fields.py [--dry-run] [--all]
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select, update

from ugc_bot.application.services.instagram_stats_collector_service import (
    _extract_analytics_fields,
)
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.models import InstagramStatsModel
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)


async def run(dry_run: bool, all_records: bool) -> int:
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

    async with session_factory() as session:
        stmt = select(InstagramStatsModel)
        if not all_records:
            stmt = stmt.where(
                InstagramStatsModel.full_name.is_(None),
                InstagramStatsModel.avg_likes.is_(None),
                InstagramStatsModel.engagement_rate.is_(None),
            )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    if not rows:
        print("No instagram_stats records to update.")
        return 0

    logger.info("Found %d records to process.", len(rows))

    updated = 0
    skipped = 0
    errors = 0

    for model in rows:
        try:
            analytics = _extract_analytics_fields(
                model.raw_response or {},
                model.followers_count,
                model.follows_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to extract analytics for user_id=%s: %s",
                model.user_id,
                exc,
            )
            errors += 1
            continue

        has_data = any(
            [
                analytics.full_name is not None,
                analytics.is_professional_account is not None,
                analytics.is_business_account is not None,
                analytics.category_name is not None,
                analytics.external_url is not None,
                analytics.avg_likes is not None,
                analytics.avg_comments is not None,
                analytics.avg_video_views is not None,
                analytics.engagement_rate is not None,
                analytics.posting_frequency_days is not None,
                analytics.total_video_count is not None,
                analytics.total_photo_count is not None,
                analytics.video_ratio is not None,
                analytics.followers_to_follows_ratio is not None,
                analytics.comments_to_likes_ratio is not None,
            ]
        )

        if not has_data:
            logger.debug(
                "No analytics extractable for user_id=%s, skipping.",
                model.user_id,
            )
            skipped += 1
            continue

        if dry_run:
            logger.info(
                "Would update user_id=%s: full_name=%r engagement_rate=%s avg_likes=%s",
                model.user_id,
                analytics.full_name,
                analytics.engagement_rate,
                analytics.avg_likes,
            )
            updated += 1
            continue

        async with session_factory() as session:
            await session.execute(
                update(InstagramStatsModel)
                .where(InstagramStatsModel.user_id == model.user_id)
                .values(
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
            )
            await session.commit()
            updated += 1
            logger.info("Updated user_id=%s", model.user_id)

    print(
        f"Processed {len(rows)}: updated={updated}, skipped={skipped}, errors={errors} "
        f"(dry_run={dry_run})"
    )
    if dry_run and updated > 0:
        print("Run without --dry-run to apply changes.")
    return 0 if errors == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill analytics fields in instagram_stats from raw_response. "
            "By default, only processes rows where full_name, avg_likes, and "
            "engagement_rate are all NULL."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be updated, do not change the database.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_records",
        help="Re-process all records, even those with existing analytics fields.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run, all_records=args.all_records))


if __name__ == "__main__":
    sys.exit(main())
