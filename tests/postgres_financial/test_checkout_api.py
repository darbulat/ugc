"""Trusted checkout transactions and native provider boundaries."""

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.container import Container
from ugc_bot.miniapp.api import router


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _checkout_env.__wrapped__(financial_pg_engine):
        yield env


def signed(env, **extra):
    return dict(
        init_data=generate_init_data(
            "test-token", int(env["actor"].external_id), "client"
        ),
        platform="telegram",
        **extra,
    )


def app(env, container):
    value = FastAPI()
    value.include_router(router, prefix="/miniapp")
    value.state.config = container._config
    value.state.dispatcher = container.build_bot_services()
    value.state.bot = AsyncMock()
    value.state.bot.create_invoice_link.return_value = (
        "https://t.me/$actual_stored_link"
    )
    return value


@pytest.mark.asyncio
async def test_signed_checkout_real_factory_and_rebuilt_receipt(checkout_env):
    env = checkout_env
    container = Container(env["config"])
    application = app(env, container)
    url = f"/miniapp/api/financial/orders/{env['order'].order_id}/invoice"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                url, json=signed(env, operation_key="checkout")
            )
            assert response.status_code == 200, response.text
            assert response.json()["amount_minor"] == 1740000
            assert (
                response.json()["invoice_url"]
                == "https://t.me/$actual_stored_link"
            )
            repeated = await client.post(
                url, json=signed(env, operation_key="checkout")
            )
            assert repeated.json() == response.json()
            assert application.state.bot.create_invoice_link.await_count == 1
            forged = await client.post(
                url, json=signed(env, operation_key="forged", paid=True)
            )
            assert forged.status_code == 422
            wrong = await client.post(
                url,
                json=dict(signed(env, operation_key="wrong"), init_data="bad"),
            )
            assert wrong.status_code == 401
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_admin_review_context_and_command_use_actual_signed_admin(
    checkout_env,
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    async with env["transactions"].transaction() as session:
        auth = await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "query",
            1740000,
            "RUB",
            session=session,
        )
    container = Container(env["config"])
    application = app(env, container)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            url = (
                "/miniapp/api/financial/checkout/orders/"
                f"{env['order'].order_id}/review-context"
            )
            denied = await client.post(url, json=signed(env))
            assert denied.status_code == 403
            admin = dict(
                init_data=generate_init_data(
                    "test-token", int(env["admin"].telegram_id), "admin"
                ),
                platform="telegram",
            )
            response = await client.post(url, json=admin)
            assert response.status_code == 200, response.text
            context = response.json()
            assert context["authorization_id"] == str(auth["authorization_id"])
            assert context["paid_receipt_count"] == 0
            payload = dict(
                admin,
                operation_key="manual-disposition",
                expected_version=context["version"],
                decision="confirmed_not_charged",
                reason="Actual manual provider reconciliation reviewed",
                evidence_reference="provider-case:actual-review-reference",
            )
            review_url = (
                "/miniapp/api/financial/checkout/authorizations/"
                f"{auth['authorization_id']}/review"
            )
            reviewed = await client.post(review_url, json=payload)
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["source"] == "manual_admin_review"
            repeated = await client.post(review_url, json=payload)
            assert repeated.json() == reviewed.json()
            changed = await client.post(
                review_url,
                json=dict(
                    payload,
                    reason="Changed manual justification for same command",
                ),
            )
            assert changed.status_code == 409
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_unknown_link_explicit_retry_and_rebuilt_factory_use_intent(
    checkout_env,
):
    from uuid import uuid4

    env = checkout_env
    container = Container(env["config"])
    application = app(env, container)
    prefix = f"/miniapp/api/financial/orders/{env['order'].order_id}"
    application.state.bot.create_invoice_link.side_effect = TimeoutError(
        "uncertain creation"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            unknown = await client.post(
                prefix + "/invoice", json=signed(env, operation_key="unknown")
            )
            assert (
                unknown.status_code == 200
                and unknown.json()["invoice_state"] == "unknown"
            ), unknown.text
            application.state.bot.create_invoice_link.side_effect = None
            ready = await client.post(
                prefix + "/invoice/retry",
                json=signed(
                    env,
                    operation_key="explicit",
                    previous_attempt_id=unknown.json()["attempt_id"],
                ),
            )
            assert (
                ready.status_code == 200
                and ready.json()["invoice_state"] == "ready"
            )
            bad = await client.post(
                prefix + "/checkout-status?paid=true", json=signed(env)
            )
            assert bad.status_code == 422
            missing = await client.post(
                f"/miniapp/api/financial/orders/{uuid4()}/checkout-status",
                json=signed(env),
            )
            assert missing.status_code == 404
            missing_review = await client.post(
                f"/miniapp/api/financial/checkout/orders/{uuid4()}/review-context",
                json={
                    "init_data": generate_init_data(
                        "test-token", int(env["admin"].telegram_id), "admin"
                    ),
                    "platform": "telegram",
                },
            )
            assert missing_review.status_code == 404
        rebuilt = Container(env["config"])
        rebuilt_app = app(env, rebuilt)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=rebuilt_app),
                base_url="http://testserver",
            ) as client:
                replay = await client.post(
                    prefix + "/invoice/retry",
                    json=signed(
                        env,
                        operation_key="explicit",
                        previous_attempt_id=unknown.json()["attempt_id"],
                    ),
                )
                assert (
                    replay.status_code == 200 and replay.json() == ready.json()
                )
                rebuilt_app.state.bot.create_invoice_link.assert_not_awaited()
        finally:
            await rebuilt.session_factory.kw["bind"].dispose()
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_native_webhook_commit_worker_and_signed_status(
    checkout_env, monkeypatch
):
    import asyncio
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )
    from ugc_bot.infrastructure.db.checkout_models import INBOX, INBOX_STATE
    from ugc_bot.telegram_webhook_app import app as webhook

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    container = Container(env["config"])
    application = app(env, container)
    processor = PaidReceiptProcessor(
        env["checkout_repo"],
        env["transactions"],
        application.state.dispatcher["payment_service"],
    )
    application.state.dispatcher["checkout_paid_processor"] = processor
    config = env["config"].model_copy(
        update={
            "webhook": env["config"].webhook.model_copy(
                update={"webhook_secret": "actual-synthetic-secret"}
            )
        }
    )
    for key, value in {
        "config": config,
        "dispatcher": application.state.dispatcher,
        "bot": application.state.bot,
        "webhook_semaphore": asyncio.Semaphore(1),
    }.items():
        monkeypatch.setattr(webhook.state, key, value, raising=False)
    at = env["clock"].at + timedelta(seconds=2)
    body = {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "date": int(at.timestamp()),
            "chat": {"id": int(env["actor"].external_id), "type": "private"},
            "from": {
                "id": int(env["actor"].external_id),
                "is_bot": False,
                "first_name": "Actual",
            },
            "successful_payment": {
                "currency": "RUB",
                "total_amount": 1740000,
                "invoice_payload": str(env["order"].order_id),
                "telegram_payment_charge_id": "actual-tg-source",
                "provider_payment_charge_id": "actual-provider-source",
            },
        },
    }
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=webhook, raise_app_exceptions=False
            ),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/webhook/telegram",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": "actual-synthetic-secret"
                },
                json=body,
            )
            assert response.status_code == 200, response.text
        with Session(env["pg"]) as db:
            assert (
                db.execute(
                    select(INBOX_STATE.c.state)
                    .join(INBOX)
                    .where(INBOX.c.order_id == env["order"].order_id)
                ).scalar_one()
                == "pending"
            )
        assert await processor.run_once()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/miniapp/api/financial/orders/{env['order'].order_id}/checkout-status",
                json=signed(env),
            )
            assert response.status_code == 200, response.text
            assert response.json()["capture_state"] == "confirmed"
            assert response.json()["captured_at"].startswith(
                at.replace(microsecond=0).isoformat()[:19]
            )
    finally:
        await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["checkout-status", "invoice"])
async def test_signed_successor_receives_no_original_checkout_proof(
    checkout_env, endpoint
):
    from sqlalchemy import update
    from sqlalchemy.orm import Session

    from ugc_bot.infrastructure.db.models import OrderModel

    env = checkout_env
    order_id = env["order"].order_id
    await env["checkout"].request_invoice(order_id, env["actor"], "issue")
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(advertiser_id=env["admin"].user_id)
        )
    container = Container(env["config"])
    application = app(env, container)
    payload = dict(
        init_data=generate_init_data(
            "test-token", int(env["admin"].telegram_id), "successor"
        ),
        platform="telegram",
    )
    if endpoint == "invoice":
        payload["operation_key"] = "successor-key"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/miniapp/api/financial/orders/{order_id}/{endpoint}",
                json=payload,
            )
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot["capture_state"] == "unavailable"
        assert snapshot["invoice_url"] is None
        assert snapshot["amount_minor"] is None
        assert snapshot["authorization_id"] is None
        assert snapshot["attempt_id"] is None
        application.state.bot.create_invoice_link.assert_not_awaited()
    finally:
        await container.session_factory.kw["bind"].dispose()
