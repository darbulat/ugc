"""E2E tests with real Telegram bot via Telethon.

Requires: bot running with webhook, TELEGRAM_E2E_* env vars set.
"""

import os

import pytest

from tests.e2e.telegram_client import (
    get_last_bot_message,
    send_to_bot,
)


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_start_command(telegram_user_client, telegram_e2e_config) -> None:
    """Send /start and verify welcome text and role keyboard context."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    await send_to_bot(telegram_user_client, bot_username, "/start")
    text = await get_last_bot_message(telegram_user_client, entity, timeout=15)

    assert text is not None, "Bot did not reply to /start"
    assert "UMC" in text
    assert "сервис для UGC" in text or "UGC" in text


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_role_selection_creator(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Choose creator role and verify next step."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    await send_to_bot(telegram_user_client, bot_username, "/start")
    await get_last_bot_message(telegram_user_client, entity, timeout=15)

    await send_to_bot(telegram_user_client, bot_username, "Я креатор")
    text = await get_last_bot_message(telegram_user_client, entity, timeout=15)

    assert text is not None, "Bot did not reply to role selection"
    assert "UGC" in text or "креатор" in text


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_role_selection_advertiser(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Choose advertiser role and verify next step."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)

    await send_to_bot(telegram_user_client, bot_username, "/start")
    await get_last_bot_message(telegram_user_client, entity, timeout=15)

    await send_to_bot(
        telegram_user_client, bot_username, "Мне нужны UGC‑креаторы"
    )
    text = await get_last_bot_message(telegram_user_client, entity, timeout=15)

    assert text is not None, "Bot did not reply to role selection"
    assert "профиль" in text or "роль" in text or "UGC" in text
