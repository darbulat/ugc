#!/usr/bin/env python3
"""Convert blogger prices from RUB to the blogger's national currency.

blogger_profiles.currency is assumed to already be correct in the DB.
The script finds profiles where currency != 'RUB' and converts the price
(still stored in RUB) to match. Only price is updated.

For each such profile the script:
  1. Reads the target currency from blogger_profiles.currency.
  2. Multiplies price by the hardcoded RUB → target exchange rate.
  3. Rounds the result to the nearest rounding_step for that currency.
  4. Writes the new price back to blogger_profiles (currency unchanged).

IMPORTANT: Exchange rates below are approximate. Update them before running
in production.  Run with --dry-run first to review the planned changes.

Usage:
    uv run python scripts/convert_blogger_currencies.py --dry-run
    uv run python scripts/convert_blogger_currencies.py
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import select, update

from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.models import BloggerProfileModel
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded exchange rates: 1 RUB → X <target_currency>
# Update these before running in production.
# ---------------------------------------------------------------------------
_RATES: dict[str, float] = {
    "BYN": 0.033,  # 1 BYN ≈ 30 RUB
    "KZT": 5.7,  # 1 KZT ≈ 0.175 RUB
    "KGS": 1.2,  # 1 KGS ≈ 0.83 RUB
    "AMD": 4.0,  # 1 AMD ≈ 0.25 RUB
    "UZS": 135.0,  # 1 UZS ≈ 0.0074 RUB
    "GEL": 0.037,  # 1 GEL ≈ 27 RUB
}

# Rounding step per currency (prices are rounded to a "nice" multiple).
_ROUND_STEP: dict[str, float] = {
    "BYN": 1.0,
    "KZT": 100.0,
    "KGS": 10.0,
    "AMD": 100.0,
    "UZS": 1000.0,
    "GEL": 1.0,
}


def _convert_price(price_rub: float, currency: str) -> float:
    """Convert *price_rub* to *currency* and round to a nice step."""
    rate = _RATES[currency]
    step = _ROUND_STEP.get(currency, 1.0)
    raw = price_rub * rate
    rounded = round(raw / step) * step
    # Never return less than one rounding step.
    return max(rounded, step)


async def run(dry_run: bool) -> int:
    """Main logic. Returns exit code."""
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

    # Fetch all rows that need updating in one query.
    # currency is already correct on the profile; price is still in RUB.
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    BloggerProfileModel.user_id,
                    BloggerProfileModel.price,
                    BloggerProfileModel.currency,
                )
                .where(BloggerProfileModel.currency.not_in(["RUB"]))
                .order_by(
                    BloggerProfileModel.currency,
                    BloggerProfileModel.user_id,
                )
            )
        ).all()

    if not rows:
        print("No blogger profiles require price conversion.")
        return 0

    # Check that we have exchange rates for all currencies present.
    needed_currencies = {r.currency for r in rows}
    missing = needed_currencies - set(_RATES)
    if missing:
        print(
            f"ERROR: No exchange rate defined for currencies: {missing}. "
            "Add entries to _RATES in this script and re-run.",
            file=sys.stderr,
        )
        return 1

    updated = 0
    skipped = 0

    for user_id, price_rub, currency in rows:
        new_price = _convert_price(float(price_rub), currency)

        logger.info(
            "user_id=%s  currency=%s  price: %.2f → %.2f",
            user_id,
            currency,
            price_rub,
            new_price,
        )

        if dry_run:
            updated += 1
            continue

        async with session_factory() as session:
            await session.execute(
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == user_id)
                .values(price=new_price)
            )
            await session.commit()
        updated += 1

    noun = "Would update" if dry_run else "Updated"
    print(
        f"Processed {len(rows)} profile(s): "
        f"{noun} {updated}, skipped {skipped} "
        f"(dry_run={dry_run})"
    )
    if dry_run and updated > 0:
        print("Run without --dry-run to apply changes.")
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Convert blogger prices from RUB to the blogger's national"
            " currency. Assumes blogger_profiles.currency is already"
            " correct. Only updates price for profiles whose currency"
            " is not RUB. Update _RATES in the script before running."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be changed, do not modify the database.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
