"""Telethon fixtures and helpers for Telegram E2E tests."""

import asyncio
import os
import time
from pathlib import Path

import pytest
import pytest_asyncio


def _get_e2e_config() -> dict[str, str]:
    """Read Telegram E2E config from env."""
    return {
        "api_id": os.environ.get("TELEGRAM_E2E_API_ID", ""),
        "api_hash": os.environ.get("TELEGRAM_E2E_API_HASH", ""),
        "phone": os.environ.get("TELEGRAM_E2E_PHONE", ""),
        "bot_username": os.environ.get("TELEGRAM_E2E_BOT_USERNAME", ""),
    }


def _has_e2e_credentials() -> bool:
    """True if all required E2E credentials are set."""
    cfg = _get_e2e_config()
    return all(cfg[k] for k in ("api_id", "api_hash", "phone", "bot_username"))


async def send_to_bot(client, bot_username: str, text: str):
    """Send a message to the bot and return the sent message."""
    entity = await client.get_entity(bot_username)
    return await client.send_message(entity, text)


async def get_last_bot_message(
    client, entity, timeout: float = 15.0, after_message=None
) -> str | None:
    """Wait for and return a message from the bot in the chat.

    If after_message is set (the message we just sent), returns the first
    bot message with id > after_message.id so we get the reply to our send.
    Otherwise returns the most recent bot message (may be stale).
    """
    after_id = after_message.id if after_message is not None else None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await client.get_messages(entity, limit=10)
        for msg in messages:
            if (
                not msg.out
                and msg.text
                and (after_id is None or msg.id > after_id)
            ):
                return msg.text
        await asyncio.sleep(0.5)
    return None


async def send_and_get_reply(
    client, entity, bot_username: str, text: str, timeout: float = 20.0
) -> str | None:
    """Send a message to the bot and return the bot's reply."""
    sent = await send_to_bot(client, bot_username, text)
    return await get_last_bot_message(
        client, entity, timeout=timeout, after_message=sent
    )


async def get_bot_message_containing(
    client, entity, substring: str, timeout: float = 30.0
) -> str | None:
    """Wait for a bot message that contains the given substring."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await client.get_messages(entity, limit=10)
        for msg in messages:
            if not msg.out and msg.text and substring in msg.text:
                return msg.text
        await asyncio.sleep(1)
    return None


@pytest.fixture(scope="session")
def telegram_e2e_config() -> dict[str, str]:
    """E2E config from env (read-only)."""
    return _get_e2e_config()


# Function scope: client must run in same event loop as test (Telethon).
@pytest_asyncio.fixture
async def telegram_user_client(telegram_e2e_config):
    """Create Telethon client for E2E tests.

    Requires TELEGRAM_E2E_API_ID, TELEGRAM_E2E_API_HASH, TELEGRAM_E2E_PHONE.
    First run may require interactive login code.
    """
    if not _has_e2e_credentials():
        pytest.skip(
            "Telegram E2E credentials not set. "
            "Set TELEGRAM_E2E_API_ID, API_HASH, PHONE, BOT_USERNAME."
        )

    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    SessionDir = Path(__file__).resolve().parent / ".telethon_session"
    SessionDir.mkdir(exist_ok=True)
    session_path = str(SessionDir / "e2e_user")

    client = TelegramClient(
        SQLiteSession(session_path),
        int(telegram_e2e_config["api_id"]),
        telegram_e2e_config["api_hash"],
    )
    await client.start(phone=telegram_e2e_config["phone"])
    try:
        yield client
    finally:
        await client.disconnect()
