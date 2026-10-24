"""Trusted checkout transactions and native provider boundaries."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.domain.checkout import CheckoutActor, NativePaidReceipt
from ugc_bot.infrastructure.db.checkout_models import (
    AUTHORIZATIONS,
    FACTS,
)
from ugc_bot.infrastructure.db.models import (
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _checkout_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "blocked",
        "no_country",
        "foreign_identity",
        "paused",
        "provider_missing",
        "missing_operation",
    ],
)
async def test_preflight_rejects_without_remote_call_or_intent(
    checkout_env, case
):
    env = checkout_env
    checkout, actor, key = env["checkout"], env["actor"], "new"
    if case in {"blocked", "no_country"}:
        values = (
            {"status": "blocked"} if case == "blocked" else {"country": None}
        )
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor.user_id)
                .values(**values)
            )
    elif case == "foreign_identity":
        actor = replace(actor, external_id="different-native-identity")
    elif case == "paused":
        checkout = replace(checkout, core_enabled=False)
    elif case == "provider_missing":
        env["config"].bot.telegram_provider_token = ""
    else:
        key = ""
    with pytest.raises((PermissionError, ValueError)):
        await checkout.request_invoice(env["order"].order_id, actor, key)
    env["gateway"].create_link.assert_not_awaited()
    with Session(env["pg"]) as db:
        assert (
            db.get(OutboxEventModel, intent_id(env["order"].order_id)) is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payer,amount,currency",
    [
        ("wrong", 1740000, "RUB"),
        (None, 1740001, "RUB"),
        (None, 1740000, "USD"),
        (None, True, "RUB"),
    ],
)
async def test_native_precheckout_rejects_wrong_real_source(
    checkout_env, payer, amount, currency
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    with pytest.raises((PermissionError, ValueError)):
        async with env["transactions"].transaction() as session:
            await env["checkout_repo"].authorize(
                env["order"].order_id,
                payer or env["actor"].external_id,
                "query",
                amount,
                currency,
                session=session,
            )
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(AUTHORIZATIONS).where(
                    AUTHORIZATIONS.c.order_id == env["order"].order_id
                )
            ).first()
            is None
        )


@pytest.mark.asyncio
async def test_authorization_rollback_does_not_leave_a_payment_permission(
    checkout_env,
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    with pytest.raises(RuntimeError):
        async with env["transactions"].transaction() as session:
            await env["checkout_repo"].authorize(
                env["order"].order_id,
                env["actor"].external_id,
                "rolled-back",
                1740000,
                "RUB",
                session=session,
            )
            raise RuntimeError("abort before native approval")
    async with env["transactions"].transaction() as session:
        approved = await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "real-query",
            1740000,
            "RUB",
            session=session,
        )
    assert approved["query_id"] == "real-query"


@pytest.mark.asyncio
async def test_source_facts_are_append_only_even_when_a_mutation_matches_rows(
    checkout_env,
):
    env = checkout_env
    for table in FACTS:
        column = next(iter(table.primary_key.columns))
        async with env["transactions"].transaction() as session:
            with pytest.raises(DBAPIError, match="checkout_evidence_immutable"):
                await session.execute(
                    table.update().values({column.name: uuid4()})
                )
            await session.rollback()
        async with env["transactions"].transaction() as session:
            with pytest.raises(DBAPIError, match="checkout_evidence_immutable"):
                await session.execute(table.delete())
            await session.rollback()


@pytest.mark.asyncio
async def test_manual_review_denies_nonadmin_and_stale_version(checkout_env):
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
    status = await env["checkout"].status(env["order"].order_id, env["actor"])
    for actor, version, error in [
        (env["actor"], status["version"], PermissionError),
        (
            CheckoutActor(
                env["admin"].user_id, "telegram", env["admin"].telegram_id
            ),
            status["version"] - 1,
            ValueError,
        ),
    ]:
        with pytest.raises(error):
            async with env["transactions"].transaction() as session:
                await env["checkout_repo"].review_authorization(
                    auth["authorization_id"],
                    actor,
                    "review",
                    version,
                    "Actual provider reviewed manual disposition",
                    "provider-case:real-review-reference",
                    session=session,
                )


@pytest.mark.asyncio
async def test_changed_receipt_payload_cannot_rewrite_original_native_fact(
    checkout_env,
):
    env = checkout_env
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "chat",
        "message",
        env["order"].order_id,
        "provider-id",
        "telegram-id",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(
            receipt, session=session
        )
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        async with env["transactions"].transaction() as session:
            await env["checkout_repo"].accept_receipt(
                replace(receipt, amount_minor=1), session=session
            )


@pytest.mark.asyncio
async def test_mutable_paid_status_without_capture_source_is_not_confirmation(
    checkout_env,
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(PaymentModel)
            .where(PaymentModel.order_id == env["order"].order_id)
            .values(status="paid")
        )
    status = await env["checkout"].status(env["order"].order_id, env["actor"])
    assert status["capture_state"] == "unavailable"
    assert not status["can_open"]


@pytest.mark.asyncio
async def test_precheckout_rejects_invoice_after_its_agreed_selection_due(
    checkout_env, monkeypatch
):
    from datetime import timedelta

    from ugc_bot.application.errors import OrderCreationError
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    monkeypatch.setattr(
        adapter, "now", lambda: env["clock"].at + timedelta(days=4)
    )
    with pytest.raises((ValueError, OrderCreationError)):
        async with env["transactions"].transaction() as session:
            await env["checkout_repo"].authorize(
                env["order"].order_id,
                env["actor"].external_id,
                "late-query",
                1740000,
                "RUB",
                session=session,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["core_enabled", "new_orders_enabled"])
async def test_fresh_authorization_stops_at_each_emergency_gate(
    checkout_env, gate
):
    env = checkout_env
    order_id = env["order"].order_id
    await env["checkout"].request_invoice(order_id, env["actor"], "issue")
    setattr(env["config"].financial, gate, False)
    paused = replace(env["checkout"], **{gate: False})
    assert (await paused.status(order_id, env["actor"]))["writes_paused"]
    with pytest.raises(ValueError, match="financial_disabled"):
        await paused.authorize(
            order_id, env["actor"].external_id, "fresh-paused", 1740000, "RUB"
        )
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(AUTHORIZATIONS).where(
                    AUTHORIZATIONS.c.order_id == order_id
                )
            ).first()
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["status", "invoice"])
@pytest.mark.parametrize("tracked", [True, False])
async def test_reassigned_owner_cannot_read_original_checkout_facts(
    checkout_env, path, tracked
):
    from ugc_bot.infrastructure.db.checkout_models import REQUESTS
    from ugc_bot.infrastructure.db.models import OrderModel

    env = checkout_env
    order_id = env["order"].order_id
    if tracked:
        await env["checkout"].request_invoice(order_id, env["actor"], "issue")
        await env["checkout"].authorize(
            order_id, env["actor"].external_id, "original", 1740000, "RUB"
        )
    else:
        async with env["transactions"].transaction() as session:
            await env["checkout_repo"].capture.issue(
                order_id,
                env["actor"].user_id,
                env["checkout_repo"].account,
                session=session,
            )
    successor = CheckoutActor(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(advertiser_id=successor.user_id)
        )
    result = (
        await env["checkout"].status(order_id, successor)
        if path == "status"
        else await env["checkout"].request_invoice(
            order_id, successor, "successor"
        )
    )
    assert result["capture_state"] == "unavailable"
    assert not result["can_open"]
    for name in [
        "invoice_url",
        "amount_minor",
        "captured_at",
        "attempt_id",
        "authorization_id",
    ]:
        assert result[name] is None
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(REQUESTS).where(
                    REQUESTS.c.client_id == successor.user_id,
                    REQUESTS.c.order_id == order_id,
                )
            ).first()
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_source", ["service", "repository"])
async def test_pause_preserves_exact_authorized_query_replay(
    checkout_env, pause_source
):
    env = checkout_env
    order_id = env["order"].order_id
    await env["checkout"].request_invoice(order_id, env["actor"], "issue")
    original = await env["checkout"].authorize(
        order_id, env["actor"].external_id, "original", 1740000, "RUB"
    )
    paused = env["checkout"]
    if pause_source == "service":
        paused = replace(paused, core_enabled=False, new_orders_enabled=False)
    else:
        env["config"].financial.core_enabled = False
        env["config"].financial.new_orders_enabled = False
    assert (
        await paused.authorize(
            order_id, env["actor"].external_id, "original", 1740000, "RUB"
        )
        == original
    )
    with pytest.raises(ValueError, match="financial_disabled"):
        await paused.authorize(
            order_id, env["actor"].external_id, "different", 1740000, "RUB"
        )
