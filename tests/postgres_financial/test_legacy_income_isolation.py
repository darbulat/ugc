"""AC43: actual capture, synthetic later CLOSED lifecycle, real SQL worker."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.postgres_financial import test_v1_capture
from tests.postgres_financial.test_v1_capture import (
    telegram_receipt,
)
from ugc_bot.config import AppConfig
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import build_referral_reconciliation_deps
from ugc_bot.domain.enums import MessengerType, OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.models import (
    OrderModel,
    PaymentModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.referral_reconciliation_scheduler import run_once

capture_env = test_v1_capture.capture_env


def persisted_facts(env):
    """Independent read of every column, including ledger tables."""
    with env["pg"].connect() as db:
        tables = db.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname=current_schema()"
            )
        ).scalars()
        return {
            name: db.execute(
                text(
                    f'SELECT to_jsonb(t) FROM "{name}" t '
                    "ORDER BY to_jsonb(t)::text"
                )
            )
            .scalars()
            .all()
            for name in tables
            if name not in {"referral_income_entries", "alembic_version"}
        }


def income_rows(env, order):
    with Session(env["pg"]) as db:
        return list(
            db.execute(
                select(ReferralIncomeEntryModel.__table__)
                .where(ReferralIncomeEntryModel.order_id == order)
                .order_by(ReferralIncomeEntryModel.entry_id)
            ).mappings()
        )


async def captured_closed(env):
    receipt = telegram_receipt(env)
    await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        220000,
        "RUB",
        receipt=receipt,
    )
    legacy, referrer = uuid4(), uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            UserModel(
                user_id=referrer,
                messenger_type=MessengerType.TELEGRAM,
                username="referrer",
                status="active",
            )
        )
        db.flush()
        db.add(
            UserReferralBindingModel(
                referrer_user_id=referrer, referred_user_id=env["client"]
            )
        )
        # Explicit SYNTHETIC later lifecycle; not natural completion evidence.
        db.get(OrderModel, env["order"]).status = OrderStatus.CLOSED
        db.add(
            OrderModel(
                order_id=legacy,
                advertiser_id=env["client"],
                product_link="legacy",
                offer_text="legacy",
                price=2200,
                bloggers_needed=2,
                status=OrderStatus.CLOSED,
            )
        )
        db.flush()
        db.add(
            PaymentModel(
                payment_id=uuid4(),
                order_id=legacy,
                provider="synthetic-legacy",
                status=PaymentStatus.PAID,
                amount=2200,
                currency="RUB",
                external_id=str(legacy),
            )
        )
    repos = build_repos(env["factory"])
    deps = build_referral_reconciliation_deps(
        AppConfig(), repos, SessionTransactionManager(env["factory"])
    )
    return legacy, deps


async def reconcile(deps):
    await run_once(
        deps["referral_income_entry_repo"],
        deps["recorder"],
        deps["order_repo"],
        deps["transaction_manager"],
        batch_limit=1,
    )


@pytest.mark.asyncio
async def test_reconciliation_never_creates_legacy_income_for_v1_order(
    capture_env,
):
    env = capture_env
    legacy, deps = await captured_closed(env)
    assert income_rows(env, env["order"]) == []
    assert income_rows(env, legacy) == []
    before = persisted_facts(env)
    for _ in range(3):
        await reconcile(deps)
    assert income_rows(env, env["order"]) == [], "v1 legacy income INSERT"
    legacy_rows = income_rows(env, legacy)
    assert len(legacy_rows) == 1
    assert legacy_rows[0]["commission_amount"] > 0
    await reconcile(deps)
    assert income_rows(env, legacy) == legacy_rows
    assert persisted_facts(env) == before


async def add_creator(env, legacy):
    from ugc_bot.infrastructure.db.models import InteractionModel

    creator = uuid4()
    with Session(env["pg"]) as db, db.begin():
        referrer = db.scalar(
            select(UserReferralBindingModel.referrer_user_id).where(
                UserReferralBindingModel.referred_user_id == env["client"]
            )
        )
        db.add(
            UserModel(
                user_id=creator,
                username="creator",
                status="active",
                messenger_type=MessengerType.TELEGRAM,
            )
        )
        db.flush()
        db.add(
            UserReferralBindingModel(
                referrer_user_id=referrer, referred_user_id=creator
            )
        )
        for order in [env["order"], legacy]:
            db.add(
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order,
                    blogger_id=creator,
                    advertiser_id=env["client"],
                    status="ok",
                )
            )
    return creator


@pytest.mark.asyncio
async def test_creator_discovery_excludes_v1_before_batch_limit(capture_env):
    env = capture_env
    legacy, deps = await captured_closed(env)
    await add_creator(env, legacy)
    before = persisted_facts(env)
    candidates = await deps[
        "referral_income_entry_repo"
    ].find_missing_creator_income(limit=1)
    assert [row.order_id for row in candidates] == [legacy], (
        "v1 consumes creator batch"
    )
    await reconcile(deps)
    assert income_rows(env, env["order"]) == []
    rows = income_rows(env, legacy)
    assert len(rows) == 2
    assert {r["income_type"] for r in rows} == {"creator", "advertiser"}
    await reconcile(deps)
    assert income_rows(env, legacy) == rows
    assert persisted_facts(env) == before


@pytest.mark.asyncio
async def test_direct_recorders_and_facade_skip_versioned_income(capture_env):
    from ugc_bot.application.services.referral_income_service import (
        ReferralIncomeService,
    )

    env = capture_env
    legacy, deps = await captured_closed(env)
    creator = await add_creator(env, legacy)
    repos = build_repos(env["factory"])
    facade = ReferralIncomeService(
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        order_repo=repos["order_repo"],
        payment_repo=repos["payment_repo"],
        interaction_repo=repos["interaction_repo"],
        user_repo=repos["user_repo"],
        payout_request_repo=repos["payout_request_repo"],
        referral_income_entry_repo=repos["referral_income_entry_repo"],
        contact_pricing_repo=repos["pricing_repo"],
    )
    before = persisted_facts(env)
    for recorder in [deps["recorder"], facade]:
        for order_id in [env["order"], legacy]:
            async with env["factory"].begin() as session:
                order = await deps["order_repo"].get_by_id(
                    order_id, session=session
                )
                await recorder.record_creator_referral_income(
                    order, creator, "ru", session=session
                )
                await recorder.record_advertiser_referral_income(
                    order, env["client"], "ru", session=session
                )
    assert income_rows(env, env["order"]) == [], (
        "direct v1 legacy income INSERT"
    )
    assert len(income_rows(env, legacy)) == 2
    assert persisted_facts(env) == before
