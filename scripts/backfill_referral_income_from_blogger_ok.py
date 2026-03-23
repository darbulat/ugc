#!/usr/bin/env python3
"""Backfill referral_income_entries for interactions where from_blogger = '✅ Всё прошло нормально'.

One-time script. Finds interactions with that exact blogger feedback value,
looks up the order, and calls record_creator_referral_income for each.
Idempotent: the recorder skips entries that already exist.

Usage:
    uv run python scripts/backfill_referral_income_from_blogger_ok.py [--dry-run]
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select

from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.infrastructure.db.models import InteractionModel
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)

BLOGGER_FEEDBACK = "✅ Всё прошло нормально"


async def run(dry_run: bool = False) -> int:
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

    recorder = ReferralIncomeRecorder(
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        user_repo=repos["user_repo"],
        referral_income_entry_repo=repos["referral_income_entry_repo"],
        contact_pricing_repo=repos["pricing_repo"],
        payment_repo=repos["payment_repo"],
    )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(InteractionModel.order_id, InteractionModel.blogger_id)
                .where(InteractionModel.from_blogger == BLOGGER_FEEDBACK)
                .order_by(InteractionModel.order_id)
            )
        ).all()

    logger.info("Found %d interactions with blogger feedback OK", len(rows))

    recorded = 0
    skipped = 0
    errors = 0

    for row in rows:
        order_id, blogger_id = row.order_id, row.blogger_id

        order = await repos["order_repo"].get_by_id(order_id)
        if order is None:
            logger.warning("Order %s not found, skipping", order_id)
            skipped += 1
            continue

        advertiser = await repos["user_repo"].get_by_id(order.advertiser_id)
        if advertiser is None or not advertiser.country:
            logger.warning(
                "Advertiser %s has no country for order %s, skipping",
                order.advertiser_id,
                order_id,
            )
            skipped += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would record creator income: order=%s creator=%s country=%s",
                order_id,
                blogger_id,
                advertiser.country,
            )
            recorded += 1
            continue

        try:
            await recorder.record_creator_referral_income(
                order=order,
                creator_id=blogger_id,
                advertiser_country_code=advertiser.country,
            )
            recorded += 1
        except Exception:
            logger.error(
                "Failed for order=%s creator=%s",
                order_id,
                blogger_id,
                exc_info=True,
            )
            errors += 1

    logger.info(
        "Done. recorded=%d skipped=%d errors=%d dry_run=%s",
        recorded,
        skipped,
        errors,
        dry_run,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without writing to DB",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
