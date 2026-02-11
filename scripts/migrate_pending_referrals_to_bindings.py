#!/usr/bin/env python3
"""Migrate user_referral_pending to user_referral_bindings for advertisers.

For each pending referral, if the referred user has a filled advertiser profile,
creates a record in user_referral_bindings and removes the pending record.
Useful to backfill bindings for advertisers who registered before referral
payouts for advertisers were implemented.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.entities import UserReferralBinding
from ugc_bot.infrastructure.db.models import UserReferralPendingModel
from ugc_bot.infrastructure.db.session import create_session_factory


async def run(dry_run: bool) -> int:
    """Create bindings from pending for users with advertiser profile.
    Remove pending record after creating binding (or if binding already exists).
    """
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
    advertiser_repo = repos["advertiser_repo"]
    binding_repo = repos["user_referral_binding_repo"]
    pending_repo = repos["user_referral_pending_repo"]

    async with session_factory() as session:
        result = await session.execute(select(UserReferralPendingModel))
        pending_models = result.scalars().all()
    if not pending_models:
        print("No pending referrals found.")
        return 0

    created = 0
    removed = 0
    skipped_no_profile = 0
    skipped_has_binding = 0

    for model in pending_models:
        user_id: UUID = model.user_id
        referrer_user_id: UUID = model.referrer_user_id
        created_at: datetime = model.created_at

        async with session_factory() as session:
            profile = await advertiser_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                skipped_no_profile += 1
                continue

            existing = await binding_repo.get_by_referred_user(
                user_id, session=session
            )
            if existing is not None:
                if not dry_run:
                    await pending_repo.delete_by_user(user_id, session=session)
                    await session.commit()
                removed += 1
                skipped_has_binding += 1
                continue

            if dry_run:
                print(
                    "[dry-run] Would create binding "
                    f"referrer={referrer_user_id} referred={user_id} "
                    "and remove pending"
                )
                created += 1
                continue

            binding = UserReferralBinding(
                referrer_user_id=referrer_user_id,
                referred_user_id=user_id,
                created_at=created_at
                if created_at.tzinfo
                else created_at.replace(tzinfo=timezone.utc),
            )
            await binding_repo.save(binding, session=session)
            await pending_repo.delete_by_user(user_id, session=session)
            await session.commit()
            created += 1
            removed += 1

    print(
        f"Created bindings: {created}, removed pending: {removed}, "
        f"skipped (no advertiser profile): {skipped_no_profile}, "
        f"skipped (already had binding): {skipped_has_binding}"
    )
    if dry_run and created > 0:
        print("Run without --dry-run to apply changes.")
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Migrate pending referrals to bindings for users with "
            "advertiser profile."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be done, do not change the database.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
