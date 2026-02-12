#!/usr/bin/env python3
"""Nullify role_chosen_at for users who have neither creator nor advertiser profile.

Use after changing logic so that role_chosen_at is set only when a profile
is created, to fix users who had role_chosen_at set on role choice but never
completed registration.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from ugc_bot.config import load_config
from ugc_bot.container import repository_factory
from ugc_bot.domain.entities import User
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.session import create_session_factory


async def run(dry_run: bool) -> int:
    """Set role_chosen_at to NULL for users with no blogger and no advertiser profile."""
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
    user_repo = repos["user_repo"]
    blogger_repo = repos["blogger_repo"]
    advertiser_repo = repos["advertiser_repo"]

    async with session_factory() as session:
        result = await session.execute(
            select(UserModel.user_id).where(
                UserModel.role_chosen_at.isnot(None)
            )
        )
        user_ids = [row[0] for row in result.scalars().all()]

    if not user_ids:
        print("No users with role_chosen_at set.")
        return 0

    updated_count = 0
    for user_id in user_ids:
        async with session_factory() as session:
            user = await user_repo.get_by_id(user_id, session=session)
            if user is None:
                continue
            blogger = await blogger_repo.get_by_user_id(
                user_id, session=session
            )
            advertiser = await advertiser_repo.get_by_user_id(
                user_id, session=session
            )
            if blogger is not None or advertiser is not None:
                continue

            if not dry_run:
                updated_user = User(
                    user_id=user.user_id,
                    external_id=user.external_id,
                    messenger_type=user.messenger_type,
                    username=user.username,
                    status=user.status,
                    issue_count=user.issue_count,
                    created_at=user.created_at,
                    role_chosen_at=None,
                    last_role_reminder_at=user.last_role_reminder_at,
                    telegram=user.telegram,
                    admin=user.admin,
                    referral_code=user.referral_code,
                    referral_payout_rate=getattr(
                        user, "referral_payout_rate", None
                    ),
                )
                await user_repo.save(updated_user, session=session)
                await session.commit()
            updated_count += 1

    print(
        f"Users with role_chosen_at set but no profile: {updated_count} "
        f"(dry_run={dry_run})"
    )
    if dry_run and updated_count > 0:
        print("Run without --dry-run to apply changes.")
    return 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Set role_chosen_at to NULL for users who have neither "
            "a creator (blogger) nor an advertiser profile."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many would be updated, do not change the database.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
