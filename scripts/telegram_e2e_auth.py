"""One-time Telethon login for E2E tests.

Saves session to tests/e2e/.telethon_session. Run interactively
(e.g. make e2e-telegram-docker-auth) and enter the code from Telegram.
Session is reused by pytest e2e_telegram tests so they do not prompt.
"""

import asyncio
import os
import sys
from pathlib import Path


def main() -> None:
    api_id = os.environ.get("TELEGRAM_E2E_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_E2E_API_HASH", "").strip()
    phone = os.environ.get("TELEGRAM_E2E_PHONE", "").strip()
    if not api_id or not api_hash or not phone:
        print(
            "Set TELEGRAM_E2E_API_ID, TELEGRAM_E2E_API_HASH, "
            "TELEGRAM_E2E_PHONE",
            file=sys.stderr,
        )
        sys.exit(1)

    session_dir = (
        Path(__file__).resolve().parent.parent
        / "tests"
        / "e2e"
        / ".telethon_session"
    )
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = str(session_dir / "e2e_user")

    async def run() -> None:
        from telethon import TelegramClient
        from telethon.sessions import SQLiteSession

        client = TelegramClient(
            SQLiteSession(session_path),
            int(api_id),
            api_hash,
        )
        await client.start(phone=phone)
        await client.disconnect()
        print("Session saved. Run make e2e-telegram-docker without code.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
