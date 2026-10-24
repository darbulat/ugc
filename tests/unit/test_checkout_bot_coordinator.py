"""Trusted checkout transactions and native provider boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.application.services.test_checkout_service import setup
from ugc_bot.bot.telegram.handlers.checkout import send_checkout_if_v1
from ugc_bot.domain.enums import MessengerType


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_coordinator",
        "legacy",
        "missing_order",
        "max",
        "rejected",
        "confirmed",
        "unknown",
    ],
)
async def test_bot_checkout_only_uses_current_v1_coordinator(case):
    checkout, repo, *_ = setup()
    payments = SimpleNamespace(
        get_order=AsyncMock(
            return_value=None
            if case == "missing_order"
            else SimpleNamespace(
                financial_version=None if case == "legacy" else "v1"
            )
        )
    )
    messenger = SimpleNamespace(send_text=AsyncMock())
    incoming = SimpleNamespace(
        chat_id="123",
        user=SimpleNamespace(
            external_id="123",
            messenger_type=MessengerType.MAX
            if case == "max"
            else MessengerType.TELEGRAM,
        ),
    )
    repo.prepare.return_value = {
        "capture_state": "confirmed" if case == "confirmed" else "not_recorded",
        "invoice_state": "unknown",
        "can_open": False,
    }
    if case == "rejected":
        repo.prepare.side_effect = ValueError("not payable")
    config = SimpleNamespace(
        bot=SimpleNamespace(telegram_provider_token="provider"),
        market=SimpleNamespace(receipt_service_description="receipt"),
    )
    result = await send_checkout_if_v1(
        uuid4(),
        SimpleNamespace(user_id=uuid4()),
        incoming,
        SimpleNamespace(bot=AsyncMock()),
        messenger,
        payments,
        None if case == "missing_coordinator" else checkout,
        config,
        "en",
    )
    assert result == (case not in {"legacy", "missing_order"})
    if result:
        messenger.send_text.assert_awaited_once()
    else:
        messenger.send_text.assert_not_awaited()
