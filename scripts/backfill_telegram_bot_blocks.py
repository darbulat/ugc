#!/usr/bin/env python3
"""Import confirmed Telegram block refusals from a completed reminder ledger."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    record_bot_availability,
)


def read_blocks(path: Path) -> list[tuple[UUID, str, datetime]]:
    ledger = json.loads(path.read_text(encoding="utf-8"))
    completed = datetime.fromisoformat(ledger["completed_at"])
    if completed.utcoffset() is None or completed > datetime.now(timezone.utc):
        raise ValueError("Invalid ledger completion time")
    seen = set()
    blocks = []
    for row in ledger["cohort"]:
        if row["platform"] != "telegram" or row["state"] != "blocked_at_send":
            continue
        user_id = UUID(row["id"])
        chat_id = row["route"]
        attempted = datetime.fromisoformat(row["attempted_at"])
        if (
            user_id in seen
            or not chat_id.isascii()
            or not chat_id.isdecimal()
            or chat_id.startswith("0")
            or attempted.utcoffset() is None
            or attempted > completed
        ):
            raise ValueError("Invalid or duplicate Telegram refusal")
        seen.add(user_id)
        blocks.append(
            (
                user_id,
                chat_id,
                attempted.astimezone(timezone.utc).replace(microsecond=0),
            )
        )
    return blocks


async def import_blocks(blocks: list[tuple[UUID, str, datetime]]) -> int:
    container = Container(load_config())
    transactions = container.transaction_manager
    if transactions is None:
        raise RuntimeError("Database transaction manager is required")
    try:
        inserted = 0
        for user_id, chat_id, attempted in blocks:
            inserted += await record_bot_availability(
                transactions,
                platform=MessengerType.TELEGRAM,
                external_id=chat_id,
                expected_user_id=user_id,
                occurred_at=attempted,
            )
        return inserted
    finally:
        await container.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        blocks = read_blocks(args.ledger)
    except (ValueError, KeyError, OSError, AttributeError, TypeError):
        parser.error("Could not read a completed reminder ledger")
    print(f"Confirmed Telegram refusals: {len(blocks)}")
    if args.apply:
        inserted = asyncio.run(import_blocks(blocks))
        print(
            f"Inserted: {inserted}; "
            f"already present or unmatched: {len(blocks) - inserted}"
        )


if __name__ == "__main__":
    main()
