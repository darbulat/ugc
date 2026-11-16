"""Real Postgres payment-channel contention and provider capture lifecycle."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from tests.helpers.correction_approval_pg import ApprovalRuntime
from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.services.browser_checkout import BrowserCheckoutService
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
)
from ugc_bot.domain.browser_checkout import (
    BROWSER_PROVIDER,
    BrowserInvoice,
    BrowserPayment,
    InvoiceUnavailable,
)
from ugc_bot.domain.checkout import NativePaidReceipt
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.browser_checkout_models import BROWSER_ATTEMPTS
from ugc_bot.infrastructure.db.checkout_models import AUTHORIZATIONS
from ugc_bot.infrastructure.db.models import (
    OrderModel,
    OutboxEventModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.order_notice_models import ORDER_NOTICE_EVENTS
from ugc_bot.infrastructure.db.repositories.browser_checkout import (
    SqlBrowserCheckout,
)
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
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
            SqlAlchemyOrderNoticeRepository(),
        ),
        env["transactions"],
        gateway,
        lambda amount, currency: {"items": []},
        public_base_url="https://bot.example.test",
        can_create=True,
    )


async def offer(checkout, oid):
    await checkout.offer(oid)
    view = await checkout.view(oid)
    return UUID(view["url"].rsplit("#", 1)[1])


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
    token = await offer(checkout, oid)
    assert await offer(checkout, oid) == token
    gateway.observe.assert_not_awaited()
    assert (await env["checkout"].status(oid, actor))["can_open"] is True
    assert (await checkout.buyer_view(token))["state"] == "available"
    task = asyncio.create_task(checkout.start(token, "buyer@example.com"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await checkout.start(token, "other@example.com")
        assert await checkout.buyer_view(token) == {
            "state": "creating",
            "url": None,
        }
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
    assert await checkout.buyer_view(token) == {"state": "pending", "url": URL}
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
        paid_events = await session.execute(
            select(ORDER_NOTICE_EVENTS.c.order_id).where(
                ORDER_NOTICE_EVENTS.c.order_id == oid,
                ORDER_NOTICE_EVENTS.c.event_kind == "paid",
            )
        )
        assert paid_events.scalars().all() == [oid]
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
    gateway = AsyncMock()
    checkout = service(env, gateway)
    token = await offer(checkout, oid)
    await env["checkout"].authorize(oid, actor.external_id, "q", 1740000, "RUB")
    assert (await checkout.buyer_view(token))["state"] == "telegram_pending"
    with pytest.raises(OrderCreationError, match="telegram_payment_pending"):
        await checkout.switch_to_browser(oid)
    assert (await checkout.view(oid))["telegram_disabled"] is False
    with pytest.raises(OrderCreationError, match="telegram_payment_pending"):
        await checkout.start(token, "buyer@example.com")
    receipt = NativePaidReceipt(
        actor.external_id,
        "trusted-chat",
        "native-message",
        oid,
        "provider-paid",
        "telegram-paid",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(
            receipt, session=session
        )
    payment = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    assert await PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payment
    ).run_once()
    assert await checkout.buyer_view(token) == {"state": "paid", "url": None}
    gateway.observe.assert_not_awaited()


@pytest.mark.asyncio
async def test_switch_keeps_link_and_blocks_telegram_before_browser_starts(
    checkout_env,
):
    env = checkout_env
    oid, actor = env["order"].order_id, env["actor"]
    await env["checkout"].request_invoice(oid, actor, "native")
    gateway = AsyncMock()
    checkout = service(env, gateway)
    token = await offer(checkout, oid)
    assert (await env["checkout"].status(oid, actor))["can_open"]

    await asyncio.gather(
        checkout.switch_to_browser(oid), checkout.switch_to_browser(oid)
    )
    admin_view = await checkout.view(oid)
    assert admin_view["telegram_disabled"] and admin_view["url"].endswith(
        str(token)
    )
    assert (await checkout.buyer_view(token))["state"] == "available"
    gateway.observe.assert_not_awaited()
    native = await env["checkout"].status(oid, actor)
    assert native["reason"] == "browser_payment_active"
    assert not native["can_open"] and native["invoice_url"] is None
    with pytest.raises(ValueError, match="browser_payment_active"):
        await env["checkout"].authorize(
            oid, actor.external_id, "old-link", 1740000, "RUB"
        )
    # Old app versions on a rolling deployment cannot insert an approval.
    with pytest.raises(IntegrityError, match="browser_payment_active"):
        async with env["transactions"].transaction() as session:
            await session.execute(
                insert(AUTHORIZATIONS).values(
                    authorization_id=uuid4(),
                    order_id=oid,
                    account=env["config"].bot.telegram_payment_account_id,
                    query_id="old-instance",
                    payer_external_id=actor.external_id,
                    client_id=actor.user_id,
                    amount_minor=1740000,
                    currency="RUB",
                    intent_id=intent_id(oid),
                    approved_at=datetime.now(timezone.utc),
                )
            )


@pytest.mark.asyncio
async def test_browser_available_after_telegram_link_timeout(checkout_env):
    env = checkout_env
    oid, actor = env["order"].order_id, env["actor"]
    env["gateway"].create_link.side_effect = TimeoutError
    native = await env["checkout"].request_invoice(oid, actor, "native")
    assert native["invoice_state"] == "unknown"
    assert not native["can_open"]
    gateway = AsyncMock()
    gateway.observe.return_value = BrowserInvoice(
        f"in-{uuid4()}", "pending", URL
    )
    checkout = service(env, gateway)
    token = await offer(checkout, oid)
    assert (await checkout.buyer_view(token))["state"] == "available"
    gateway.observe.assert_not_awaited()
    await checkout.start(token, "buyer@example.com")
    attempt = gateway.observe.await_args.args[0]
    assert attempt.request["payment_data"]["receipt"]["customer"] == {
        "email": "buyer@example.com"
    }
    assert await checkout.buyer_view(token) == {"state": "pending", "url": URL}


@pytest.mark.asyncio
async def test_paid_legacy_projection_cannot_issue_browser_invoice(
    checkout_env,
):
    env = checkout_env
    oid, actor = env["order"].order_id, env["actor"]
    await env["checkout"].request_invoice(oid, actor, "native")
    gateway = AsyncMock()
    checkout = service(env, gateway)
    token = await offer(checkout, oid)
    async with env["transactions"].transaction() as session:
        await session.execute(
            update(PaymentModel)
            .where(PaymentModel.order_id == oid)
            .values(
                status=PaymentStatus.PAID, paid_at=datetime.now(timezone.utc)
            )
        )
    assert (await checkout.buyer_view(token))["state"] == "paid"
    with pytest.raises(
        OrderCreationError, match="browser_payment_quote_not_unpaid"
    ):
        await checkout.start(token, "buyer@example.com")
    with pytest.raises(OrderCreationError, match="order_not_payable"):
        await checkout.offer(oid)
    gateway.observe.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_or_closed_order_cannot_issue_invoice(checkout_env):
    env = checkout_env
    gateway = AsyncMock()
    checkout = service(env, gateway)
    missing = uuid4()
    assert await checkout.view(missing) is None
    with pytest.raises(LookupError, match="order_not_found"):
        await checkout.offer(missing)
    with pytest.raises(LookupError, match="browser_link_not_found"):
        await checkout.buyer_view(missing)
    with pytest.raises(LookupError, match="browser_link_not_found"):
        await checkout.start(missing, "buyer@example.com")
    oid = env["order"].order_id
    token = await offer(checkout, oid)
    async with env["transactions"].transaction() as session:
        order = await session.get(OrderModel, oid)
        order.status = OrderStatus.CLOSED
    assert await checkout.view(oid) is None
    with pytest.raises(OrderCreationError, match="order_not_payable"):
        await checkout.offer(oid)
    with pytest.raises(OrderCreationError, match="order_not_payable"):
        await checkout.start(token, "buyer@example.com")
    assert (await checkout.buyer_view(token))["state"] == "unavailable"
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
    token = await offer(checkout, oid)
    await checkout.start(token, "buyer@example.com")
    assert (await checkout.view(oid))["state"] == "creating"
    await due(env)
    await checkout.start(token, "different@example.com")
    initial, replay = [call.args[0] for call in gateway.observe.await_args_list]
    assert initial.attempt_id == replay.attempt_id
    assert initial.request == replay.request
    assert (await checkout.view(oid))["state"] == "pending"
    await due(env)
    assert await checkout.run_once(oid)
    assert (await checkout.view(oid))["state"] == "canceled"
    assert (await env["checkout"].status(oid, actor))["can_open"] is True
