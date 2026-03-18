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


_FLOOD_WAIT_SLEEP_THRESHOLD = 120  # seconds; skip if wait > this


async def send_to_bot(client, bot_username: str, text: str):
    """Send a message to the bot and return the sent message."""
    from telethon.errors import FloodWaitError

    entity = await client.get_entity(bot_username)
    try:
        return await client.send_message(entity, text)
    except FloodWaitError as e:
        if e.seconds > _FLOOD_WAIT_SLEEP_THRESHOLD:
            raise
        await asyncio.sleep(e.seconds + 1)
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
    client,
    entity,
    substring: str | tuple[str, ...],
    timeout: float = 30.0,
) -> str | None:
    """Wait for a bot message that contains the given substring(s).
    substring may be a single str or a tuple of alternatives (e.g. for i18n).
    """
    substrings = (substring,) if isinstance(substring, str) else substring
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await client.get_messages(entity, limit=10)
        for msg in messages:
            if not msg.out and msg.text:
                for sub in substrings:
                    if sub in msg.text:
                        return msg.text
        await asyncio.sleep(1)
    return None


def _has_inline_buttons(msg) -> bool:
    """Return True if message has inline keyboard (callback buttons)."""
    if msg.out or not getattr(msg, "reply_markup", None):
        return False
    rm = msg.reply_markup
    return getattr(rm, "rows", None) is not None


def _message_has_callback_button(msg, callback_data: str | bytes) -> bool:
    """True if message has an inline button with the given callback_data."""
    if not _has_inline_buttons(msg):
        return False
    want = (
        callback_data.encode()
        if isinstance(callback_data, str)
        else callback_data
    )
    rm = msg.reply_markup
    rows = getattr(rm, "rows", None) or []
    for row in rows:
        buttons = (
            row
            if isinstance(row, (list, tuple))
            else getattr(row, "buttons", [])
        )
        for btn in buttons:
            btn_data = getattr(btn, "data", None)
            if btn_data is not None and btn_data == want:
                return True
    return False


async def _get_last_bot_message_with_inline(
    client, entity, callback_data: str | None = None
):
    """Return the most recent bot message with inline keyboard, or None.

    If callback_data is set, only return a message that has a button with
    that callback_data (avoids clicking the wrong message).
    """
    messages = await client.get_messages(entity, limit=15)
    for msg in messages:
        if (
            not msg.out
            and _has_inline_buttons(msg)
            and (
                callback_data is None
                or _message_has_callback_button(msg, callback_data)
            )
        ):
            return msg
    return None


async def click_inline_and_get_reply(
    client, entity, callback_data: str, timeout: float = 20.0
) -> str | None:
    """Find last bot message with inline keyboard, click by callback_data,
    return bot reply text."""
    msg = await _get_last_bot_message_with_inline(
        client, entity, callback_data=callback_data
    )
    if msg is None:
        return None
    data = (
        callback_data.encode()
        if isinstance(callback_data, str)
        else callback_data
    )
    await msg.click(data=data)
    return await get_last_bot_message(
        client, entity, timeout=timeout, after_message=msg
    )


async def click_inline_by_index_and_get_reply(
    client, entity, index: int = 0, timeout: float = 20.0
) -> str | None:
    """Find last bot message with inline keyboard, click by index,
    return bot reply text."""
    msg = await _get_last_bot_message_with_inline(client, entity)
    if msg is None:
        return None
    await msg.click(index)
    return await get_last_bot_message(
        client, entity, timeout=timeout, after_message=msg
    )


async def get_group_message_containing(
    client,
    chat_id: int | str,
    substrings: str | tuple[str, ...],
    after_id: int = 0,
    timeout: float = 30.0,
) -> str | None:
    """Wait for a message in a group/channel containing the given substring(s).

    Args:
        client: Telethon TelegramClient.
        chat_id: Group/channel ID (int or string, e.g. -1001234567890).
        substrings: One or more substrings to match (OR logic).
        after_id: Only consider messages with id > after_id.
        timeout: Seconds to wait before giving up.

    Returns the matching message text, or None on timeout.
    """
    if isinstance(substrings, str):
        substrings = (substrings,)
    entity = await client.get_entity(int(chat_id))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await client.get_messages(entity, limit=10)
        for msg in messages:
            if msg.id <= after_id:
                continue
            text = getattr(msg, "text", None) or ""
            caption = getattr(msg, "message", None) or ""
            content = text or caption
            if any(sub in content for sub in substrings):
                return content
        await asyncio.sleep(1)
    return None


async def get_latest_group_message_id(
    client,
    chat_id: int | str,
) -> int:
    """Return the id of the most recent message in a group/channel.

    Returns 0 if the chat is empty.
    """
    entity = await client.get_entity(int(chat_id))
    messages = await client.get_messages(entity, limit=1)
    if messages:
        return messages[0].id
    return 0


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
