#!/usr/bin/env python3
"""Delete users from the E2E database so tests start with a clean state.

Uses E2E_DATABASE_URL (required). All tables with FK to users use ON DELETE
CASCADE, so deleting users removes blogger/advertiser profiles, orders, etc.

With --telegram or E2E_CLEAN_TELEGRAM: deletes only the user whose telegram
username (after normalization) matches. Otherwise deletes all users.

Usage:
  E2E_DATABASE_URL=postgresql+psycopg://user:pass@host/db \\
    python scripts/clean_e2e_users.py
  E2E_DATABASE_URL=... E2E_CLEAN_TELEGRAM=darbulat python scripts/clean_e2e_users.py
  E2E_DATABASE_URL=... python scripts/clean_e2e_users.py --telegram darbulat --dry-run
"""

import asyncio
import os
import sys

from sqlalchemy import text

from ugc_bot.infrastructure.db.session import create_session_factory


def _normalize_telegram(value: str | None) -> str:
    """Normalize telegram username (same as in repositories.get_by_telegram)."""
    return (value or "").strip().lstrip("@").lower()


async def run(dry_run: bool, telegram: str | None) -> int:
    """Delete users: all or only the one matching telegram. Returns exit code."""
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
    by_telegram = bool(telegram)
    normalized = _normalize_telegram(telegram) if telegram else ""
    if by_telegram and not normalized:
        print(
            "E2E_CLEAN_TELEGRAM / --telegram must be a non-empty username.",
            file=sys.stderr,
        )
        return 1

    async with session_factory() as session:
        if by_telegram:
            # Match telegram same way as repositories: LOWER(TRIM(LTRIM(telegram,'@')))
            sel = text(
                "SELECT COUNT(*) FROM users WHERE LOWER(LTRIM(TRIM(COALESCE(telegram, '')), '@')) = :norm"
            )
            del_sql = text(
                "DELETE FROM users WHERE LOWER(LTRIM(TRIM(COALESCE(telegram, '')), '@')) = :norm"
            )
            if dry_run:
                result = await session.execute(sel, {"norm": normalized})
                count = result.scalar_one()
                print(
                    f"Would delete {count} user(s) with telegram = {telegram!r}. Run without --dry-run to apply."
                )
                return 0
            result = await session.execute(del_sql, {"norm": normalized})
        else:
            if dry_run:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM users")
                )
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
        description="Delete users from E2E DB (before Telegram E2E tests)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many users would be deleted.",
    )
    parser.add_argument(
        "--telegram",
        metavar="USERNAME",
        default=os.environ.get("E2E_CLEAN_TELEGRAM", "").strip() or None,
        help="Delete only the user with this telegram username (or set E2E_CLEAN_TELEGRAM).",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run, telegram=args.telegram))


if __name__ == "__main__":
    sys.exit(main())
