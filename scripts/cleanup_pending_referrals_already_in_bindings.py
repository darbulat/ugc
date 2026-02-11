#!/usr/bin/env python3
"""Remove pending referral records that already have a binding.

For each row in user_referral_pending, if user_id exists as referred_user_id
in user_referral_bindings, delete the pending record. Use after migrations
or to fix duplicates when a binding was created but pending was not removed.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.infrastructure.db.models import UserReferralPendingModel
from ugc_bot.infrastructure.db.session import create_session_factory


async def run(dry_run: bool) -> int:
    """Delete pending referrals whose user_id already has a binding."""
    config = load_config()
    if not config.db.database_url:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 1

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    repos = repository_factory.build_repos(session_factory)
    binding_repo = repos["user_referral_binding_repo"]
    pending_repo = repos["user_referral_pending_repo"]

    async with session_factory() as session:
        result = await session.execute(select(UserReferralPendingModel))
        pending_models = result.scalars().all()

    if not pending_models:
        print("No pending referrals found.")
        return 0

    removed = 0
    skipped = 0

    for model in pending_models:
        user_id = model.user_id

        async with session_factory() as session:
            existing = await binding_repo.get_by_referred_user(
                user_id, session=session
            )
            if existing is None:
                skipped += 1
                continue

            if not dry_run:
                await pending_repo.delete_by_user(user_id, session=session)
                await session.commit()
            removed += 1

    print(
        f"Removed pending (already in bindings): {removed}, "
        f"skipped (no binding): {skipped}"
    )
    if dry_run and removed > 0:
        print("Run without --dry-run to apply changes.")
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Remove pending referral records for users that already "
            "have a record in user_referral_bindings."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report what would be deleted, do not change the database.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
