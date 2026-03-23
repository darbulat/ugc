#!/usr/bin/env python3
"""Backfill referral_income_entries for interactions where from_blogger = '✅ Всё прошло нормально'.

One-time script. Finds interactions with that exact blogger feedback value and
creates creator referral income entries for each.

Idempotent: recorder skips entries that already exist.

Usage:
    uv run python scripts/backfill_referral_income_from_blogger_ok.py [--dry-run]
"""

import argparse
import asyncio
import logging
import sys
from typing import cast

from sqlalchemy import select

from ugc_bot.application.ports import (
    ContactPricingRepository,
    PaymentRepository,
    ReferralIncomeEntryRepository,
    UserReferralBindingRepository,
    UserRepository,
)
from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.enums import ReferralIncomeType
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

    user_referral_binding_repo = cast(
        UserReferralBindingRepository, repos["user_referral_binding_repo"]
    )
    user_repo = cast(UserRepository, repos["user_repo"])
    referral_income_entry_repo = cast(
        ReferralIncomeEntryRepository, repos["referral_income_entry_repo"]
    )
    pricing_repo = cast(ContactPricingRepository, repos["pricing_repo"])
    payment_repo = cast(PaymentRepository, repos["payment_repo"])
    order_repo = cast(UserRepository, repos["order_repo"])  # type: ignore[type-var]

    recorder = ReferralIncomeRecorder(
        user_referral_binding_repo=user_referral_binding_repo,
        user_repo=user_repo,
        referral_income_entry_repo=referral_income_entry_repo,
        contact_pricing_repo=pricing_repo,
        payment_repo=payment_repo,
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
    skipped_no_binding = 0
    skipped_already_exists = 0
    skipped_no_order = 0
    skipped_no_country = 0
    skipped_no_payment = 0
    skipped_no_pricing = 0
    errors = 0

    for row in rows:
        order_id, blogger_id = row.order_id, row.blogger_id

        order = await order_repo.get_by_id(order_id)  # type: ignore[attr-defined]
        if order is None:
            logger.warning("order_id=%s not found, skipping", order_id)
            skipped_no_order += 1
            continue

        advertiser = await user_repo.get_by_id(order.advertiser_id)
        if advertiser is None or not advertiser.country:
            logger.warning(
                "advertiser=%s has no country (order=%s), skipping",
                order.advertiser_id,
                order_id,
            )
            skipped_no_country += 1
            continue

        binding = await user_referral_binding_repo.get_by_referred_user(blogger_id)
        if binding is None:
            logger.debug(
                "No referral binding for blogger=%s (order=%s), skipping",
                blogger_id,
                order_id,
            )
            skipped_no_binding += 1
            continue

        already = await referral_income_entry_repo.exists(
            order_id, binding.referrer_user_id, ReferralIncomeType.CREATOR
        )
        if already:
            logger.debug(
                "Entry already exists for order=%s referrer=%s, skipping",
                order_id,
                binding.referrer_user_id,
            )
            skipped_already_exists += 1
            continue

        payment = await payment_repo.get_by_order(order_id)
        if payment is None:
            logger.warning(
                "No payment for order=%s (blogger=%s), skipping",
                order_id,
                blogger_id,
            )
            skipped_no_payment += 1
            continue

        country = advertiser.country.lower()
        pricing = await pricing_repo.get_by_bloggers_count(
            order.bloggers_needed, country_code=country
        )
        if pricing is None:
            logger.warning(
                "No pricing for bloggers_needed=%d country=%s (order=%s), skipping",
                order.bloggers_needed,
                country,
                order_id,
            )
            skipped_no_pricing += 1
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would record: order=%s creator=%s referrer=%s country=%s",
                order_id,
                blogger_id,
                binding.referrer_user_id,
                country,
            )
            recorded += 1
            continue

        try:
            await recorder.record_creator_referral_income(
                order=order,
                creator_id=blogger_id,
                advertiser_country_code=advertiser.country,
            )
            logger.info(
                "Recorded: order=%s creator=%s referrer=%s",
                order_id,
                blogger_id,
                binding.referrer_user_id,
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
        "Done. recorded=%d | "
        "skipped: no_binding=%d already_exists=%d no_order=%d "
        "no_country=%d no_payment=%d no_pricing=%d | errors=%d | dry_run=%s",
        recorded,
        skipped_no_binding,
        skipped_already_exists,
        skipped_no_order,
        skipped_no_country,
        skipped_no_payment,
        skipped_no_pricing,
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
