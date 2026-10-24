"""Actual Container, signed MAX/TG, native ingress and same-UUID checkout."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from aiogram import Bot
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_messenger_linking_repository import (
    link_env as _link_env,
)
from ugc_bot.container import Container
from ugc_bot.domain.order_intake import OrderIntakeCommand
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    OrderModel,
    UserModel,
)
from ugc_bot.miniapp.api import router
from ugc_bot.telegram_webhook_app import app as native_app


@pytest_asyncio.fixture
async def runtime(financial_pg_engine, monkeypatch):
    async for env in _link_env.__wrapped__(financial_pg_engine):
        config = env["config"].model_copy(
            update={
                "financial": env["config"].financial.model_copy(
                    update={"core_enabled": True, "new_orders_enabled": True}
                ),
                "bot": env["config"].bot.model_copy(
                    update={
                        "telegram_provider_token": "synthetic-provider",
                        "telegram_payment_account_id": "synthetic-account-"
                        + uuid4().hex,
                    }
                ),
            }
        )
        container = Container(config)
        services = container.build_bot_services()
        bot = Bot(config.bot.bot_token)
        bot.send_message = AsyncMock()
        bot.create_invoice_link = AsyncMock(
            return_value="https://t.me/$synthetic_linked_invoice"
        )
        application = FastAPI()
        application.include_router(router, prefix="/miniapp")
        for name, value in {
            "config": config,
            "dispatcher": services,
            "bot": bot,
            "webhook_semaphore": asyncio.Semaphore(1),
        }.items():
            setattr(application.state, name, value)
            monkeypatch.setattr(native_app.state, name, value, raising=False)
        try:
            yield dict(
                env,
                actual_config=config,
                actual_container=container,
                services=services,
                bot=bot,
                app=application,
            )
        finally:
            await bot.session.close()
            await container.session_factory.kw["bind"].dispose()


def signed(env, platform="max", user_id=None, **extra):
    config = env["actual_config"]
    return dict(
        init_data=generate_init_data(
            config.max_bot.token if platform == "max" else config.bot.bot_token,
            int(user_id or env["actor"].external_id),
            "Actual Client",
        ),
        platform=platform,
        **extra,
    )


async def api(env, kind, **extra):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=env["app"], raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        return await client.post(
            "/miniapp/api/messenger-links/telegram/" + kind,
            json=signed(env, **extra),
        )


def native_update(view, sender, update_id):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 25,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": sender, "type": "private"},
            "from": {
                "id": sender,
                "is_bot": False,
                "first_name": "Actual TG",
                "language_code": "en",
            },
            "text": "/start " + view["launch_url"].split("start=", 1)[1],
        },
    }


async def native(env, update, secret="synthetic-secret"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=native_app, raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        return await client.post(
            "/webhook/telegram",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": secret},
        )


async def issue_order(env):
    now = datetime.now(timezone.utc)
    policy = "linking-runtime-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=policy,
                approved_by=env["actor"].user_id,
                approved_at=now - timedelta(days=2),
                effective_from=now - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "synthetic-actual-published-terms",
                    "allowed_clients": [str(env["actor"].user_id)],
                },
            )
        )
    return await env["services"]["order_intake_service"].create(
        OrderIntakeCommand(
            client_id=env["actor"].user_id,
            operation_key="synthetic-order",
            policy_version=policy,
            product_link="https://example.test/product",
            offer_text="Actual local MAX order",
            honorarium=Decimal("999"),
            selection_due_at=now + timedelta(days=3),
            contact_reference="owner contact",
            service_mode="self_service",
        )
    )


@pytest.mark.asyncio
async def test_real_max_native_confirmation_keeps_uuid_and_tg_checkout(runtime):
    env = runtime
    order = await issue_order(env)
    response = await api(env, "challenge", operation_key="issue")
    assert response.status_code == 200, response.text
    waiting = response.json()
    assert response.headers["cache-control"] == "no-store"
    sender = uuid4().int % 10**12 + 1
    update = native_update(waiting, sender, uuid4().int % 10**12 + 1)
    accepted = await native(env, update)
    assert accepted.status_code == 200, accepted.text
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(UserModel.user_id).where(
                    UserModel.telegram_id == str(sender)
                )
            )
            is None
        )
    current = (await api(env, "status")).json()
    assert current["telegram_identity"]["id"] == str(sender)
    confirmed = await api(
        env,
        "confirm",
        challenge_id=current["challenge_id"],
        claim_id=current["claim_id"],
        expected_version=current["version"],
        operation_key="confirm",
    )
    assert confirmed.status_code == 200, confirmed.text
    assert (
        confirmed.json()["state"] == "linked"
        and confirmed.json()["launch_url"] is None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env["app"]), base_url="http://test"
    ) as client:
        invoice = await client.post(
            f"/miniapp/api/financial/orders/{order.order_id}/invoice",
            json=signed(
                env, "telegram", sender, operation_key="actual-tg-invoice"
            ),
        )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["amount_minor"] == 1500000
    env["bot"].create_invoice_link.assert_awaited_once()
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(UserModel.user_id).where(
                    UserModel.telegram_id == str(sender)
                )
            )
            == env["actor"].user_id
        )
        assert (
            db.get(OrderModel, order.order_id).advertiser_id
            == env["actor"].user_id
        )
    assert env["config"].financial.core_enabled is False


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["write", "commit"])
async def test_actual_native_storage_failure_is_503_then_replay_resumes(
    runtime,
    boundary,
):
    from ugc_bot.infrastructure.db.messenger_linking_models import (
        CLAIMS,
    )

    env = runtime
    waiting = (await api(env, "challenge", operation_key="issue")).json()
    sender = uuid4().int % 10**12 + 1
    update = native_update(waiting, sender, uuid4().int % 10**12 + 1)
    engine = env["actual_container"].session_factory.kw["bind"]

    commits = 0

    def reject_commit(conn):
        nonlocal commits
        commits += 1
        if commits == 2:
            raise RuntimeError("synthetic actual commit failure")

    def reject_claim(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().startswith("INSERT INTO messenger_link_claims"):
            raise RuntimeError("synthetic commit boundary failure")

    hook = "commit" if boundary == "commit" else "before_cursor_execute"
    callback = reject_commit if boundary == "commit" else reject_claim
    event.listen(engine.sync_engine, hook, callback)
    try:
        failed = await native(env, update)
        assert failed.status_code == 503, failed.text
    finally:
        event.remove(engine.sync_engine, hook, callback)
    env["bot"].send_message.assert_not_awaited()
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(CLAIMS.c.claim_id).where(
                    CLAIMS.c.challenge_id == waiting["challenge_id"]
                )
            )
            is None
        )
    replay = await native(env, update)
    assert replay.status_code == 200, replay.text
    current = (await api(env, "status")).json()
    assert current["state"] == "proposed"
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_actual_native_rejects_wrong_secret_without_claim(runtime):
    env = runtime
    waiting = (await api(env, "challenge", operation_key="issue")).json()
    update = native_update(
        waiting, uuid4().int % 10**12 + 1, uuid4().int % 10**12 + 1
    )
    result = await native(env, update, secret="wrong")
    assert result.status_code == 403
    assert (await api(env, "status")).json()["state"] == "waiting"
    env["bot"].send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_default_off_read_has_no_url_or_new_attachment(runtime):
    env = runtime
    waiting = (await api(env, "challenge", operation_key="issue")).json()
    off_config = env["actual_config"].model_copy(
        update={
            "messenger_linking": env[
                "actual_config"
            ].messenger_linking.model_copy(update={"enabled": False})
        }
    )
    off = Container(off_config)
    env["app"].state.dispatcher = off.build_bot_services()
    env["app"].state.config = off_config
    try:
        read = await api(env, "status")
        assert read.status_code == 200
        assert read.json()["state"] == "unavailable"
        assert read.json()["launch_url"] is None
        assert read.headers["cache-control"] == "no-store"
        revoked = await api(
            env,
            "revoke",
            challenge_id=waiting["challenge_id"],
            expected_version=waiting["version"],
            operation_key="off-revoke",
        )
        assert revoked.json()["state"] == "revoked"
    finally:
        await off.session_factory.kw["bind"].dispose()
