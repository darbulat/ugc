"""Real capture and production worker issue client pending journal entries."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_v1_capture import (
    capture_env as _capture_env,
)
from tests.postgres_financial.test_v1_capture import (
    telegram_receipt,
)
from ugc_bot.config import AppConfig
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import build_outbox_deps
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    OutboxEventModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.outbox_processor import OutboxProcessor

capture_env = _capture_env


def seed_attribution(env, *, years=0, referred=True):
    partner, stranger = uuid4(), uuid4()
    with Session(env["pg"]) as db, db.begin():
        for user_id in (partner, stranger):
            db.add(
                UserModel(
                    user_id=user_id,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic-partner",
                    status=UserStatus.ACTIVE,
                )
            )
        if years:
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(
                    created_at=datetime.now(timezone.utc)
                    - timedelta(days=365 * years)
                )
            )
        db.flush()
        if referred:
            db.add(
                UserReferralBindingModel(
                    referrer_user_id=partner, referred_user_id=env["client"]
                )
            )
    return partner, stranger


async def capture(env):
    receipt = replace(
        telegram_receipt(env), protocol_message_at=datetime.now(timezone.utc)
    )
    await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    with Session(env["pg"]) as db:
        return db.scalar(
            select(OutboxEventModel.event_id).where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )


def processor(env):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///:memory:",
            "FINANCIAL_CORE_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    deps = build_repos(env["factory"])
    publisher, kafka = build_outbox_deps(
        config, deps, SessionTransactionManager(env["factory"])
    )
    assert kafka is None
    return OutboxProcessor(publisher, None)


def rows(env, name):
    table = Base.metadata.tables[name]
    with Session(env["pg"]) as db:
        if "order_id" in table.c:
            statement = select(table).where(table.c.order_id == env["order"])
        else:
            obligations = Base.metadata.tables["financial_obligations"]
            statement = (
                select(table)
                .join(obligations, table.c.obligation_id == obligations.c.id)
                .where(obligations.c.order_id == env["order"])
            )
        return db.execute(statement).mappings().all()


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
@pytest.mark.parametrize(
    "years, expected_rate, pending", [(0, 1000, 10000), (2, 300, 3000)]
)
async def test_capture_worker_issues_selection_only_at_payment_age(
    request,
    years,
    expected_rate,
    pending,
):
    env = request.getfixturevalue("capture_env")
    partner, _ = seed_attribution(env, years=years)
    event_id = await capture(env)
    worker = processor(env)
    await worker.process_once()
    obligations = rows(env, "financial_obligations")
    assert len(obligations) == 2
    assert {row["kind"] for row in obligations} == {"client_referral"}
    assert {row["recipient_id"] for row in obligations} == {partner}
    assert {row["base_minor"] for row in obligations} == {50000}
    snapshots = rows(env, "rate_snapshots")
    assert {row["rate_bps"] for row in snapshots} == {expected_rate}
    assert {row["verified_count"] for row in snapshots} == {None}
    wallet = Base.metadata.tables["financial_wallets"]
    with Session(env["pg"]) as db:
        value = (
            db.execute(select(wallet).where(wallet.c.recipient_id == partner))
            .mappings()
            .one()
        )
        assert value["pending_minor"] == pending
        assert value["available_minor"] == 0
        assert db.get(OutboxEventModel, event_id).status == "published"
    await worker.process_once()
    assert len(rows(env, "financial_obligations")) == 2
    assert len(rows(env, "financial_movements")) == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_later_binding_correction_does_not_reassign_captured_commission(
    request,
):
    env = request.getfixturevalue("capture_env")
    partner, stranger = seed_attribution(env)
    await capture(env)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserReferralBindingModel)
            .where(UserReferralBindingModel.referred_user_id == env["client"])
            .values(referrer_user_id=stranger)
        )
    await processor(env).process_once()
    assert {
        row["recipient_id"] for row in rows(env, "financial_obligations")
    } == {partner}


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_forged_capture_recipient_cannot_create_money(request):
    env = request.getfixturevalue("capture_env")
    _, stranger = seed_attribution(env)
    event_id = await capture(env)
    with Session(env["pg"]) as db, db.begin():
        record = db.get(OutboxEventModel, event_id)
        record.payload = {**record.payload, "client_referrer_id": str(stranger)}
    await processor(env).process_once()
    assert rows(env, "financial_obligations") == []
    assert rows(env, "financial_movements") == []
    with Session(env["pg"]) as db:
        value = db.get(OutboxEventModel, event_id)
        assert value.status == "pending"
        assert "capture_attribution_mismatch" in value.last_error


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_known_absent_referrer_records_assessment_without_money(request):
    env = request.getfixturevalue("capture_env")
    seed_attribution(env, referred=False)
    event_id = await capture(env)
    await processor(env).process_once()
    assert rows(env, "financial_obligations") == []
    assert rows(env, "financial_movements") == []
    with Session(env["pg"]) as db:
        assert db.get(OutboxEventModel, event_id).status == "published"
        audit = Base.metadata.tables["financial_audit_events"]
        assert (
            db.execute(
                select(audit).where(
                    audit.c.action == "potential_basis",
                    audit.c.details["order_id"].as_string()
                    == str(env["order"]),
                )
            ).first()
            is not None
        )
