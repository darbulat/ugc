"""Native payment evidence is committed before webhook ACK or approval I/O."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from aiogram.types import PreCheckoutQuery, User

from ugc_bot.bot.telegram.handlers.payments import pre_checkout_query_handler
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.telegram_webhook_app import app


class Dispatcher(dict):
    feed_update = AsyncMock()


@pytest.mark.asyncio
async def test_paid_webhook_persists_before_ack_and_does_not_background_capture(
    monkeypatch,
):
    processor = SimpleNamespace(accept=AsyncMock(return_value=True))
    dispatcher = Dispatcher(checkout_paid_processor=processor)
    monkeypatch.setattr(
        app.state,
        "config",
        SimpleNamespace(
            webhook=SimpleNamespace(webhook_secret="synthetic-secret")
        ),
        raising=False,
    )
    monkeypatch.setattr(app.state, "dispatcher", dispatcher, raising=False)
    monkeypatch.setattr(app.state, "bot", AsyncMock(), raising=False)
    monkeypatch.setattr(
        app.state, "webhook_semaphore", asyncio.Semaphore(1), raising=False
    )
    data = {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 100, "is_bot": False, "first_name": "Actual"},
            "successful_payment": {
                "currency": "RUB",
                "total_amount": 1740000,
                "invoice_payload": str(uuid4()),
                "telegram_payment_charge_id": "native-charge",
                "provider_payment_charge_id": "provider-charge",
            },
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/webhook/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
            json=data,
        )
    assert response.status_code == 200, response.text
    processor.accept.assert_awaited_once()
    assert processor.accept.await_args.args[0].amount_minor == 1740000
    dispatcher.feed_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_precheckout_checks_actual_currency_amount_approval():
    order = uuid4()
    query = PreCheckoutQuery(
        id="actual-query",
        from_user=User(id=123, is_bot=False, first_name="Client"),
        currency="RUB",
        total_amount=1740000,
        invoice_payload=str(order),
    )
    provider = SimpleNamespace(
        confirm_pre_checkout=AsyncMock(), reject_pre_checkout=AsyncMock()
    )
    checkout = SimpleNamespace(
        authorize=AsyncMock(
            side_effect=ValueError("payment_authorization_pending")
        )
    )
    payments = SimpleNamespace(
        get_order=AsyncMock(
            return_value=SimpleNamespace(financial_version="actual-v1")
        )
    )
    await pre_checkout_query_handler(
        query,
        provider,
        TelegramEventAdapter(),
        payment_service=payments,
        checkout_service=checkout,
    )
    checkout.authorize.assert_awaited_once_with(
        order, "123", "actual-query", 1740000, "RUB"
    )
    provider.confirm_pre_checkout.assert_not_awaited()
    provider.reject_pre_checkout.assert_awaited_once()


@pytest.mark.asyncio
async def test_paid_inbox_commit_failure_is_503_even_with_webhook_error_handler(
    monkeypatch,
):
    processor = SimpleNamespace(
        accept=AsyncMock(side_effect=RuntimeError("synthetic commit failure"))
    )
    dispatcher = Dispatcher(checkout_paid_processor=processor)
    dispatcher.feed_update = AsyncMock()
    monkeypatch.setattr(
        app.state,
        "config",
        SimpleNamespace(
            webhook=SimpleNamespace(webhook_secret="synthetic-secret")
        ),
        raising=False,
    )
    monkeypatch.setattr(app.state, "dispatcher", dispatcher, raising=False)
    monkeypatch.setattr(app.state, "bot", AsyncMock(), raising=False)
    monkeypatch.setattr(
        app.state, "webhook_semaphore", asyncio.Semaphore(1), raising=False
    )
    data = {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 100, "is_bot": False, "first_name": "Actual"},
            "successful_payment": {
                "currency": "RUB",
                "total_amount": 1740000,
                "invoice_payload": str(uuid4()),
                "telegram_payment_charge_id": "native-charge",
                "provider_payment_charge_id": "provider-charge",
            },
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/webhook/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
            json=data,
        )
    assert response.status_code == 503, response.text
    dispatcher.feed_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_v1_deep_link_uses_shared_checkout_without_second_invoice(
    monkeypatch,
):
    from tests.application.services.test_checkout_service import Transactions
    from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
    from ugc_bot.application.services.checkout_service import CheckoutService
    from ugc_bot.bot.telegram.handlers import payments as handlers
    from ugc_bot.domain.enums import MessengerType

    order_id, user_id = uuid4(), uuid4()
    user = SimpleNamespace(user_id=user_id, country="ru")
    monkeypatch.setattr(
        handlers, "get_user_and_ensure_allowed", AsyncMock(return_value=user)
    )
    incoming = IncomingMessage(
        "123",
        IncomingUser("123", MessengerType.TELEGRAM),
        text=f"/start pay_{order_id}",
    )
    messenger = SimpleNamespace(send_text=AsyncMock(), send_invoice=AsyncMock())
    adapter = SimpleNamespace(from_message=lambda _: incoming)
    payments = SimpleNamespace(
        get_order=AsyncMock(
            return_value=SimpleNamespace(financial_version="actual-v1")
        ),
        validate_order_for_invoice=AsyncMock(
            side_effect=AssertionError("legacy invoice must not run")
        ),
    )
    repo = SimpleNamespace(
        prepare=AsyncMock(
            return_value={
                "invoice_state": "ready",
                "invoice_url": "https://t.me/$actual_stored",
                "capture_state": "not_recorded",
                "can_open": True,
            }
        )
    )
    checkout = CheckoutService(repo, Transactions(), None, True, True)
    config = SimpleNamespace(
        bot=SimpleNamespace(telegram_provider_token="synthetic-provider"),
        market=SimpleNamespace(receipt_service_description="receipt"),
    )
    await handlers.start_pay_order_link(
        SimpleNamespace(text=f"/start pay_{order_id}", bot=AsyncMock()),
        SimpleNamespace(),
        SimpleNamespace(
            get_advertiser_profile=AsyncMock(return_value=object())
        ),
        payments,
        config,
        SimpleNamespace(get_many=AsyncMock(return_value={})),
        messenger_client=messenger,
        event_adapter=adapter,
        checkout_service=checkout,
    )
    assert (
        messenger.send_text.await_args.kwargs["keyboard"].rows[0][0].url
        == "https://t.me/$actual_stored"
    )
    payments.validate_order_for_invoice.assert_not_awaited()
    messenger.send_invoice.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_v1_precheckout_without_coordinator_fails_closed():
    query = PreCheckoutQuery(
        id="no-coordinator",
        from_user=User(id=123, is_bot=False, first_name="Client"),
        currency="RUB",
        total_amount=1740000,
        invoice_payload=str(uuid4()),
    )
    provider = SimpleNamespace(
        confirm_pre_checkout=AsyncMock(), reject_pre_checkout=AsyncMock()
    )
    payments = SimpleNamespace(
        get_order=AsyncMock(
            return_value=SimpleNamespace(financial_version="v1")
        )
    )
    await pre_checkout_query_handler(
        query, provider, TelegramEventAdapter(), payment_service=payments
    )
    provider.confirm_pre_checkout.assert_not_awaited()
    provider.reject_pre_checkout.assert_awaited_once()
