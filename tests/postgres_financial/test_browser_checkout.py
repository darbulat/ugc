"""Real Postgres payment-channel contention and provider capture lifecycle."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tests.helpers.correction_approval_pg import ApprovalRuntime
from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.browser_checkout import BrowserCheckoutService
from ugc_bot.domain.browser_checkout import (
    BROWSER_PROVIDER,
    BrowserInvoice,
    BrowserPayment,
    InvoiceUnavailable,
)
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.browser_checkout_models import BROWSER_ATTEMPTS
from ugc_bot.infrastructure.db.models import (
    OrderModel,
    OutboxEventModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.repositories.browser_checkout import (
    SqlBrowserCheckout,
)
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)

SHOP = "123"
checkout_env = _checkout_env
INVOICE = "in-4c66fe26-67a8-470b-9bf9-3eb61cd93a82"
URL = "https://yookassa.ru/my/i/synthetic/a"


def service(env, gateway):
    return BrowserCheckoutService(
        SqlBrowserCheckout(
            env["checkout_repo"].capture,
            env["config"].bot.telegram_payment_account_id,
            SHOP,
            True,
            None,
        ),
        env["transactions"],
        gateway,
        lambda amount, currency: {"items": []},
        can_create=True,
    )


async def due(env):
    async with env["transactions"].transaction() as session:
        await session.execute(
            update(BROWSER_ATTEMPTS)
            .where(BROWSER_ATTEMPTS.c.order_id == env["order"].order_id)
            .values(next_check_at=datetime.now(timezone.utc))
        )


@pytest.mark.asyncio
async def test_browser_capture_blocks_existing_telegram_invoice(
    checkout_env,
):
    env = checkout_env
    oid = env["order"].order_id
    actor = env["actor"]
    await env["checkout"].request_invoice(oid, actor, "native")
    entered, finish = asyncio.Event(), asyncio.Event()

    async def create(attempt):
        assert attempt.invoice_id is None
        assert attempt.request["payment_data"]["amount"]["value"] == "17400.00"
        entered.set()
        await finish.wait()
        return BrowserInvoice(INVOICE, "pending", URL)

    gateway = AsyncMock()
    gateway.observe.side_effect = create
    checkout = service(env, gateway)
    task = asyncio.create_task(checkout.create(oid, "buyer@example.com"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await checkout.create(oid, "other@example.com")
        assert await checkout.view(oid) == {"state": "creating", "url": None}
        native = await env["checkout"].request_invoice(oid, actor, "native")
        assert native["reason"] == "browser_payment_active"
        assert native["invoice_url"] is None
        with pytest.raises(ValueError, match="browser_payment_active"):
            await env["checkout"].authorize(
                oid, actor.external_id, "new", 1740000, "RUB"
            )
    finally:
        finish.set()
        await task
    gateway.observe.assert_awaited_once()
    assert await checkout.view(oid) == {"state": "pending", "url": URL}
    await due(env)
    gateway.observe.side_effect = None
    gateway.observe.return_value = BrowserInvoice(
        INVOICE,
        "paid",
        payment=BrowserPayment(
            INVOICE,
            str(uuid4()),
            SHOP,
            1740000,
            datetime.now(timezone.utc),
        ),
    )
    assert await checkout.run_once(oid)
    assert not await checkout.run_once(oid)
    assert (await checkout.view(oid))["state"] == "paid"
    assert (await env["checkout"].status(oid, actor))[
        "capture_state"
    ] == "confirmed"
    async with env["transactions"].transaction() as session:
        payment = await session.scalar(
            select(PaymentModel).where(PaymentModel.order_id == oid)
        )
        assert payment.status == PaymentStatus.PAID
        assert payment.provider == BROWSER_PROVIDER
        assert (
            await session.get(OrderModel, oid)
        ).status == OrderStatus.PENDING_MODERATION
        event = await session.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(oid),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        facts = await SqlAlchemyClientEntitlementRepository().load_capture(
            event, session=session
        )
        assert facts.payment_id == payment.payment_id
    env["clock"].at = env["order"].selection_due_at + timedelta(seconds=1)
    refunds = ApprovalRuntime(
        env, {"order": env["order"], "client": actor.user_id}
    )
    requested = await refunds.execute(await refunds.request())
    approved = await refunds.execute(refunds.review(requested))
    assert approved.get("approval_id")


@pytest.mark.asyncio
async def test_existing_telegram_authorization_blocks_browser_creation(
    checkout_env,
):
    env = checkout_env
    oid, actor = env["order"].order_id, env["actor"]
    await env["checkout"].request_invoice(oid, actor, "native")
    await env["checkout"].authorize(oid, actor.external_id, "q", 1740000, "RUB")
    gateway = AsyncMock()
    checkout = service(env, gateway)
    assert (await checkout.view(oid))["state"] == "telegram_pending"
    with pytest.raises(OrderCreationError, match="telegram_payment_pending"):
        await checkout.create(oid, "buyer@example.com")
    gateway.observe.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_reuses_request_and_releases_on_cancellation(
    checkout_env,
):
    env = checkout_env
    oid, actor = env["order"].order_id, env["actor"]
    await env["checkout"].request_invoice(oid, actor, "native")
    invoice_id = f"in-{uuid4()}"
    gateway = AsyncMock()
    gateway.observe.side_effect = [
        InvoiceUnavailable("connection lost"),
        BrowserInvoice(invoice_id, "pending", URL),
        BrowserInvoice(invoice_id, "canceled"),
    ]
    checkout = service(env, gateway)
    await checkout.create(oid, "buyer@example.com")
    assert (await checkout.view(oid))["state"] == "creating"
    await due(env)
    await checkout.create(oid, "different@example.com")
    initial, replay = [call.args[0] for call in gateway.observe.await_args_list]
    assert initial.attempt_id == replay.attempt_id
    assert initial.request == replay.request
    assert (await checkout.view(oid))["state"] == "pending"
    await due(env)
    assert await checkout.run_once(oid)
    assert (await checkout.view(oid))["state"] == "canceled"
    assert (await env["checkout"].status(oid, actor))["can_open"] is True
