"""Manual sends never retry an ambiguous Telegram acceptance."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.creator_transfer_service import (
    CreatorTransferService,
)


def flow(fake_tm, *, source="reserve"):
    now = datetime.now(timezone.utc)
    attempt = dict(
        contact=dict(
            name="Автор <Анна>",
            phone=None,
            instagram="https://instagram.com/synthetic_creator/",
            telegram="synthetic_creator",
        ),
        title="ReBody",
        requested_price=Decimal("3500"),
        currency="RUB",
        source=source,
        address="123456",
    )
    repo = SimpleNamespace(
        prepare=AsyncMock(return_value=("sending", attempt)),
        finish=AsyncMock(return_value=True),
    )
    transport = SimpleNamespace(
        send=AsyncMock(return_value=DeliveryReceipt("telegram", "123456:42"))
    )
    service = CreatorTransferService(
        repo, fake_tm, transport, SimpleNamespace(now=lambda: now)
    )
    return service, repo, transport


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["reserve", "counteroffer"])
async def test_send_uses_contact_card_and_explicit_price(fake_tm, source):
    service, repo, transport = flow(fake_tm, source=source)
    assert await service.send(uuid4(), uuid4(), operator="admin:test") == "sent"
    message = transport.send.call_args.args[0]
    assert message.address == "123456"
    assert "3 500 ₽" in message.text and "Автор <Анна>" in message.text
    assert ("Цена требует согласования" in message.text) == (
        source == "counteroffer"
    )
    assert [link.url for link in message.card.links] == [
        "https://t.me/synthetic_creator",
        "https://instagram.com/synthetic_creator/",
    ]
    assert repo.finish.call_args.args[2] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["sending", "sent", "unknown"])
async def test_existing_send_is_not_repeated(fake_tm, state):
    service, repo, transport = flow(fake_tm)
    repo.prepare.return_value = state, None
    assert await service.send(uuid4(), uuid4(), operator="admin:test") == state
    transport.send.assert_not_awaited()
    repo.finish.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,state",
    [
        (DeliveryFailure("blocked", uncertain=False), "failed"),
        (DeliveryFailure("network", uncertain=True), "unknown"),
        (TimeoutError(), "unknown"),
    ],
)
async def test_transport_failures_are_saved_without_retry(
    fake_tm, error, state
):
    service, repo, transport = flow(fake_tm)
    transport.send.side_effect = error
    assert await service.send(uuid4(), uuid4(), operator="admin:test") == state
    transport.send.assert_awaited_once()
    assert repo.finish.call_args.args[2] == state


@pytest.mark.asyncio
async def test_missing_receipt_is_unknown(fake_tm):
    service, repo, transport = flow(fake_tm)
    transport.send.return_value = DeliveryReceipt("telegram", "")
    assert (
        await service.send(uuid4(), uuid4(), operator="admin:test") == "unknown"
    )
    assert repo.finish.call_args.args[-1] == "delivery_receipt_invalid"
