"""Tests for Telegram payment provider."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.infrastructure.messenger.telegram.payments import (
    TelegramPaymentProvider,
)


@pytest.mark.asyncio
async def test_confirm_pre_checkout() -> None:
    """confirm_pre_checkout calls bot.answer_pre_checkout_query with ok=True."""

    bot = MagicMock()
    bot.answer_pre_checkout_query = AsyncMock()

    provider = TelegramPaymentProvider(bot=bot)
    await provider.confirm_pre_checkout(query_id="q-123")

    bot.answer_pre_checkout_query.assert_called_once_with(
        pre_checkout_query_id="q-123",
        ok=True,
    )


@pytest.mark.asyncio
async def test_reject_pre_checkout() -> None:
    """reject_pre_checkout calls bot.answer_pre_checkout_query with ok=False."""

    bot = MagicMock()
    bot.answer_pre_checkout_query = AsyncMock()

    provider = TelegramPaymentProvider(bot=bot)
    await provider.reject_pre_checkout(
        query_id="q-456",
        error_message="Payment declined",
    )

    bot.answer_pre_checkout_query.assert_called_once_with(
        pre_checkout_query_id="q-456",
        ok=False,
        error_message="Payment declined",
    )
