"""One real SDK method call with frozen minor units, never a retry loop."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import CreateInvoiceLink

from ugc_bot.domain.checkout import PreparedInvoice
from ugc_bot.infrastructure.messenger.telegram.invoice_links import (
    TelegramInvoiceLinks,
)


@pytest.mark.asyncio
async def test_native_invoice_parameters_use_exact_platform_components():
    bot = AsyncMock()
    bot.create_invoice_link.return_value = "https://t.me/$actual_slug"
    gateway = TelegramInvoiceLinks(
        bot, "synthetic-provider", "Actual configured receipt description"
    )
    invoice = PreparedInvoice(
        uuid4(), uuid4(), "RUB", 1500000, 240000, "Actual requested brief"
    )
    assert await gateway.create_link(invoice) == "https://t.me/$actual_slug"
    sent = bot.create_invoice_link.await_args.kwargs
    assert sent["payload"] == str(invoice.order_id)
    assert sent["provider_token"] == "synthetic-provider"
    assert sent["currency"] == "RUB"
    assert [p.amount for p in sent["prices"]] == [1500000, 240000]
    assert all(type(p.amount) is int for p in sent["prices"])
    assert sent["need_email"] and sent["send_email_to_provider"]
    assert "17400.00" in sent["provider_data"]
    assert 1 <= len(sent["title"]) <= 32
    assert 1 <= len(sent["description"]) <= 255
    assert bot.create_invoice_link.await_count == 1


@pytest.mark.asyncio
async def test_native_transport_does_not_retry_an_uncertain_link_creation():
    bot = AsyncMock()
    bot.create_invoice_link.side_effect = TelegramNetworkError(
        method=CreateInvoiceLink(
            title="test",
            description="test",
            payload="test",
            currency="RUB",
            prices=[],
        ),
        message="uncertain",
    )
    gateway = TelegramInvoiceLinks(bot, "synthetic-provider", "receipt")
    with pytest.raises(TelegramNetworkError):
        await gateway.create_link(
            PreparedInvoice(uuid4(), uuid4(), "RUB", 50000, 0, "brief")
        )
    assert bot.create_invoice_link.await_count == 1


@pytest.mark.asyncio
async def test_bad_native_invoice_fails_definitely_before_remote_io():
    from ugc_bot.domain.checkout import LinkRejected

    gateway = TelegramInvoiceLinks(AsyncMock(), "", "receipt")
    with pytest.raises(LinkRejected):
        await gateway.create_link(
            PreparedInvoice(uuid4(), uuid4(), "RUB", 50000, 0, "brief")
        )
    gateway.bot.create_invoice_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_provider_definite_rejection_is_classified_without_retry():
    from aiogram.exceptions import TelegramBadRequest

    from ugc_bot.domain.checkout import LinkRejected

    bot = AsyncMock()
    bot.create_invoice_link.side_effect = TelegramBadRequest(
        method=CreateInvoiceLink(
            title="test",
            description="test",
            payload="test",
            currency="RUB",
            prices=[],
        ),
        message="invalid request",
    )
    with pytest.raises(LinkRejected):
        await TelegramInvoiceLinks(bot, "provider", "receipt").create_link(
            PreparedInvoice(uuid4(), uuid4(), "RUB", 50000, 0, "brief")
        )
    assert bot.create_invoice_link.await_count == 1
