#!/usr/bin/env python3
"""Delete all users from the E2E database so tests start with a clean state.

Uses E2E_DATABASE_URL (required). All tables with FK to users use ON DELETE
CASCADE, so deleting users removes blogger/advertiser profiles, orders, etc.

Usage:
  E2E_DATABASE_URL=postgresql+psycopg://user:pass@host/db \\
    python scripts/clean_e2e_users.py
  E2E_DATABASE_URL=... python scripts/clean_e2e_users.py --dry-run
"""

import asyncio
import os
import sys

from sqlalchemy import text

from ugc_bot.infrastructure.db.session import create_session_factory


async def run(dry_run: bool) -> int:
    """Delete all rows from users table. Returns exit code."""
    database_url = os.environ.get("E2E_DATABASE_URL", "").strip()
    if not database_url:
        print(
            "E2E_DATABASE_URL is required. Set it to the same DB the bot uses.",
            file=sys.stderr,
        )
        return 1

    if "postgresql" not in database_url and "sqlite" not in database_url:
        print(
            "E2E_DATABASE_URL must be PostgreSQL or SQLite.",
            file=sys.stderr,
        )
        return 1

    session_factory = create_session_factory(database_url)

    async with session_factory() as session:
        if dry_run:
            result = await session.execute(text("SELECT COUNT(*) FROM users"))
            count = result.scalar_one()
            print(
                f"Would delete {count} user(s). Run without --dry-run to apply."
            )
            return 0

        result = await session.execute(text("DELETE FROM users"))
        deleted = result.rowcount
        await session.commit()
        print(f"Deleted {deleted} user(s).")
    return 0


def main() -> int:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Delete all users from E2E DB (before Telegram E2E tests)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many users would be deleted.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
