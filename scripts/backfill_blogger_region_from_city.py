#!/usr/bin/env python3
"""Backfill blogger_profiles.region from city field.

No hardcoded region/city dictionary: resolve_region_from_city_field always
returns (None, "unrecognized"). This script logs each profile's city and
does not update region. To backfill region from city, use the geocoder
(Nominatim) in this script or run profile update flow which resolves
location via geocoder.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from ugc_bot.application.geography import resolve_region_from_city_field
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.models import BloggerProfileModel
from ugc_bot.infrastructure.db.session import create_async_db_engine

logger = logging.getLogger(__name__)


async def run(dry_run: bool, only_empty_region: bool) -> int:
    """Backfill region for blogger profiles from city."""
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    engine = create_async_db_engine(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with session_factory() as session:
        stmt = select(
            BloggerProfileModel.user_id,
            BloggerProfileModel.city,
            BloggerProfileModel.region,
        ).where(
            BloggerProfileModel.city.isnot(None),
            BloggerProfileModel.city != "",
        )
        if only_empty_region:
            stmt = stmt.where(BloggerProfileModel.region.is_(None))
        result = await session.execute(stmt)
        rows = list(result.all())

    if not rows:
        print("No blogger profiles to process.")
        return 0

    updated_count = 0
    multi_region_count = 0
    unrecognized_count = 0
    errors = 0

    for user_id, city, existing_region in rows:
        city_str = (city or "").strip()
        region_key, status = resolve_region_from_city_field(city_str)

        if status == "multiple":
            multi_region_count += 1
            logger.warning(
                "City in multiple regions: user_id=%s city=%r",
                user_id,
                city_str,
            )
            continue

        if status == "unrecognized":
            unrecognized_count += 1
            logger.warning(
                "Unrecognized city: user_id=%s city=%r",
                user_id,
                city_str,
            )
            continue

        assert status == "ok" and region_key is not None

        if dry_run:
            updated_count += 1
            logger.info(
                "Would set region for user_id=%s city=%r -> region=%s",
                user_id,
                city_str,
                region_key,
            )
            continue

        try:
            stmt = (
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == user_id)
                .values(
                    region=region_key,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            async with engine.begin() as conn:
                result = await conn.execute(stmt)
                rowcount = result.rowcount
            if rowcount == 0:
                logger.warning(
                    "No row updated for user_id=%s (profile missing?)",
                    user_id,
                )
                errors += 1
                continue
            updated_count += 1
            logger.info(
                "Set region for user_id=%s city=%r -> region=%s",
                user_id,
                city_str,
                region_key,
            )
        except Exception as e:
            logger.exception(
                "Failed to update user_id=%s: %s",
                user_id,
                e,
            )
            errors += 1

    print(
        f"Processed {len(rows)}: updated={updated_count}, "
        f"multi_region_logged={multi_region_count}, "
        f"unrecognized_logged={unrecognized_count}, errors={errors} "
        f"(dry_run={dry_run}, only_empty_region={only_empty_region})"
    )
    if dry_run and updated_count > 0:
        print("Run without --dry-run to apply changes.")
    return 0 if errors == 0 else 1


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Fill blogger_profiles.region from city using region_cities_data. "
            "Logs user_id and city for multi-region and unrecognized cities."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be updated.",
    )
    parser.add_argument(
        "--only-empty-region",
        action="store_true",
        help="Only update profiles where region is NULL.",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(dry_run=args.dry_run, only_empty_region=args.only_empty_region)
    )


if __name__ == "__main__":
    sys.exit(main())
