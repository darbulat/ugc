"""Exercise recovery at the API, transaction and scheduler boundaries."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ugc_bot import browser_checkout_scheduler
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.browser_checkout import BrowserCheckoutService
from ugc_bot.config import AppConfig
from ugc_bot.container.checkout_factory import build_browser_checkout
from ugc_bot.domain.browser_checkout import (
    BrowserInvoice,
    BrowserPayment,
    InvoiceRejected,
)


@asynccontextmanager
async def transaction():
    yield "synthetic-session"


def checkout_service(*, claim=None, can_create=True):
    repo = SimpleNamespace(
        reserve=AsyncMock(),
        claim=AsyncMock(return_value=claim),
        finish=AsyncMock(),
    )
    return BrowserCheckoutService(
        repo,
        SimpleNamespace(transaction=transaction),
        SimpleNamespace(observe=AsyncMock()),
        None,
        can_create=can_create,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,email,error",
    [
        (False, "buyer@example.com", "browser_payment_paused"),
        (True, " ", "browser_receipt_email_required"),
    ],
)
async def test_creation_guard_does_not_reserve_order(enabled, email, error):
    service = checkout_service(can_create=enabled)
    with pytest.raises(OrderCreationError, match=error):
        await service.create(uuid4(), email)
    service.repository.reserve.assert_not_awaited()
    service.gateway.observe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [True, False])
async def test_invoice_never_reissued_after_expiry_or_explicit_rejection(
    expired,
):
    claim = SimpleNamespace(
        invoice_id=None,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=-5 if expired else 5),
    )
    service = checkout_service(claim=claim)
    service.gateway.observe.side_effect = InvoiceRejected()
    assert await service.run_once()
    assert service.gateway.observe.await_count == (0 if expired else 1)
    service.repository.finish.assert_awaited_once_with(
        claim, None, "failed", session="synthetic-session"
    )


@pytest.mark.asyncio
async def test_provider_charge_stays_reserved_if_booking_conflicts():
    claim = SimpleNamespace(invoice_id="existing", order_id=uuid4())
    provider_payment = BrowserPayment(
        "existing", "payment", "123", 5000, datetime.now(timezone.utc)
    )
    paid = BrowserInvoice("existing", "paid", payment=provider_payment)
    service = checkout_service(claim=claim)
    service.gateway.observe.return_value = paid
    service.repository.finish.side_effect = [
        OrderCreationError("conflict"),
        None,
    ]
    assert await service.run_once()
    assert service.repository.finish.await_args.args == (
        claim,
        BrowserInvoice("existing", "review"),
        "review",
    )


def test_factory_freezes_receipt_data_and_starts_with_creation_paused():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "YOOKASSA_BROWSER_SHOP_ID": "123",
            "YOOKASSA_BROWSER_SECRET_KEY": "synthetic",
            "YOOKASSA_BROWSER_TEST_MODE": True,
            "TELEGRAM_PAYMENT_ACCOUNT_ID": "telegram",
        }
    )
    service = build_browser_checkout(
        config, object(), {"creator_identity_history_repo": object()}
    )
    assert service is not None
    assert service.gateway.shop_id == "123"
    assert service.gateway.test_mode is True
    assert service.can_create is False
    receipt = service.receipt(Decimal("5.00"), "RUB")
    assert receipt["items"][0]["amount"] == {"value": "5.00", "currency": "RUB"}


@pytest.mark.asyncio
async def test_scheduler_retries_errors_and_starts_with_issuance_paused(
    monkeypatch,
):
    checkout = SimpleNamespace(
        can_create=False,
        run_once=AsyncMock(side_effect=[RuntimeError("network"), True]),
    )
    config = SimpleNamespace(
        financial=SimpleNamespace(yookassa_browser_shop_id="123")
    )
    container = SimpleNamespace(build_browser_checkout=Mock(return_value=None))
    assert (
        browser_checkout_scheduler.start_reconciliation(config, container) == []
    )
    container.build_browser_checkout.return_value = checkout
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(browser_checkout_scheduler.asyncio, "sleep", sleep)
    [task] = browser_checkout_scheduler.start_reconciliation(config, container)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [c.args[0] for c in sleep.await_args_list] == [5, 0.1]
