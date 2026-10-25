"""Persisted payment proofs, concurrent retries and immutable history."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_order_intake import (
    command,
    service,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as _intake_env,
)
from ugc_bot.application.services.subscription_service import (
    SubscriptionService,
)
from ugc_bot.infrastructure.db.models import ManagerOrderModel
from ugc_bot.infrastructure.db.repositories.subscriptions import (
    SqlAlchemySubscriptionRepository,
)
from ugc_bot.infrastructure.db.subscription_models import SUBSCRIPTIONS

intake_env = _intake_env


async def prepared(env):
    result = await service(env).create(command(env))
    member = await create_test_user(
        env["repos"]["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    with Session(env["pg"]) as db, db.begin():
        db.add(
            ManagerOrderModel(
                user_id=member.user_id,
                order_id=result.order_id,
                created_at=env["clock"].at,
            )
        )
    subscriptions = SubscriptionService(
        SqlAlchemySubscriptionRepository(),
        env["container"].transaction_manager,
        env["clock"],
    )
    tariff = "tariff-" + uuid4().hex
    await subscriptions.execute(
        env["admin"].user_id,
        "publish",
        tariff,
        dict(
            version=tariff,
            title="Synthetic test-only own network",
            price_minor=10000,
            duration_days=30,
            campaign_limit=5,
            recipient_limit=100,
            terms_reference="synthetic-test-terms",
            reason="Synthetic integration fixture",
        ),
    )
    payload = dict(
        member_id=str(member.user_id),
        tariff_version=tariff,
        amount_minor=10000,
        currency="RUB",
        paid_at=env["clock"].at.isoformat(),
        payment_reference="synthetic-bank-" + uuid4().hex,
        evidence_reference="synthetic-not-real-paid-pilot",
        evidence_hash="a" * 64,
        reason="Synthetic reviewed receipt fixture",
        pilot=True,
    )
    return subscriptions, member, payload


@pytest.mark.asyncio
async def test_sql_paid_subscription_replay_expiry_and_immutable_evidence(
    intake_env,
):
    env = intake_env
    subscriptions, member, payload = await prepared(env)
    operation = "payment-" + uuid4().hex
    first = await subscriptions.execute(
        env["admin"].user_id, "accept_payment", operation, payload
    )
    assert (
        await subscriptions.execute(
            env["admin"].user_id, "accept_payment", operation, payload
        )
        == first
    )
    own = await subscriptions.view(member.user_id)
    assert own["subscription"]["state"] == "active"
    assert "payments" not in own
    with Session(env["pg"]) as db:
        row = (
            db.execute(
                select(SUBSCRIPTIONS).where(
                    SUBSCRIPTIONS.c.operation_key == operation
                )
            )
            .mappings()
            .one()
        )
        assert (
            row["payload"]["evidence_reference"]
            == "synthetic-not-real-paid-pilot"
        )
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(
                text(
                    "UPDATE manager_subscription_events SET result=result "
                    "WHERE event_id=:id"
                ),
                {"id": row["event_id"]},
            )
    env["clock"].at += timedelta(days=30)
    assert (await subscriptions.view(member.user_id))["subscription"][
        "state"
    ] == "expired"


@pytest.mark.asyncio
async def test_payment_reference_cannot_fund_two_periods(
    intake_env,
):
    env = intake_env
    subscriptions, member, payload = await prepared(env)
    results = await asyncio.gather(
        *(
            subscriptions.execute(
                env["admin"].user_id,
                "accept_payment",
                "race-" + uuid4().hex,
                payload,
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert (await subscriptions.view(member.user_id))["subscription"][
        "until"
    ] == (env["clock"].at + timedelta(days=30)).isoformat()


@pytest.mark.asyncio
async def test_admin_demotion_blocks_paid_command_replay(intake_env):
    env = intake_env
    subscriptions, _, payload = await prepared(env)
    key = "demotion-" + uuid4().hex
    await subscriptions.execute(
        env["admin"].user_id, "accept_payment", key, payload
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            text("UPDATE users SET admin=false WHERE user_id=:id"),
            {"id": env["admin"].user_id},
        )
    with pytest.raises(PermissionError, match="current_admin"):
        await subscriptions.execute(
            env["admin"].user_id, "accept_payment", key, payload
        )
