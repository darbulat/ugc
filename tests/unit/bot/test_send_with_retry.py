"""Tests for send_with_retry on_bot_blocked callback."""

import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.bot.handlers.utils import send_with_retry

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_on_bot_blocked_called_when_forbidden() -> None:
    """on_bot_blocked callback is invoked when TelegramForbiddenError."""
    forbidden_exc = TelegramForbiddenError(
        method=SendMessage(chat_id=0, text=""),
        message="Forbidden: bot was blocked by the user",
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=forbidden_exc)
    on_blocked = AsyncMock()

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=3,
        delay_seconds=0,
        logger=logger,
        on_bot_blocked=on_blocked,
    )

    assert result is False
    on_blocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_bot_blocked_not_called_on_other_error() -> None:
    """on_bot_blocked is NOT called for unrelated errors."""
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=RuntimeError("network"))
    on_blocked = AsyncMock()

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=1,
        delay_seconds=0,
        logger=logger,
        on_bot_blocked=on_blocked,
    )

    assert result is False
    on_blocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_bot_blocked_none_does_not_raise() -> None:
    """No on_bot_blocked callback is fine."""
    forbidden_exc = TelegramForbiddenError(
        method=SendMessage(chat_id=0, text=""),
        message="Forbidden: bot was blocked by the user",
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=forbidden_exc)

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=1,
        delay_seconds=0,
        logger=logger,
    )

    assert result is False
