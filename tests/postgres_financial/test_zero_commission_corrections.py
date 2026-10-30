"""A zero referral audit is refundable only with its captured source proof."""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.helpers.corrections import captured_order
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    service,
)
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    OutboxEventModel,
)

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_zero_correction_sql_rejects_forged_source_rate_and_scope(
    intake_env,
):
    env = intake_env
    version = "zero-proof-" + uuid4().hex
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "retain_earned"
    )
    with Session(env["pg"]) as db, db.begin():
        old = db.get(FinancialPolicyVersionModel, env["policy"])
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=old.approved_by,
                approved_at=old.approved_at,
                effective_from=old.effective_from,
                refund_window_seconds=3600,
                rules=old.rules
                | {
                    "selection_minor": 1,
                    "accompaniment_minor": 120000,
                    "refund_rules": rules.to_document(),
                },
            )
        )
    request = command(env, policy_version=version, position_count=10)
    order = await service(env).create(request)
    facts = await captured_order(env, existing=(request, order))
    with Session(env["pg"]) as db:
        event = db.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(order.order_id),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        fact = event.payload["attribution_history"]["fact"]
    registered = datetime.fromisoformat(fact["registered_at"])
    captured = facts["capture_at"]
    changes = [
        {},  # Exact legitimate zero assessment is the positive control.
        {"recipient_id": facts["stranger"]},
        {"rate_bps": 300},
        {"registered_at": registered - timedelta(days=1)},
        {"base_minor": 2},
        {"event_id": str(uuid4())},
        {"policy_version": "not-the-captured-policy"},
        {"rate_source": "override", "override_id": uuid4(), "rate_bps": 1},
        {"snapshot_at": captured + timedelta(seconds=1)},
        {"payment_id": uuid4()},
    ]
    repo = env["repos"]["financial_ledger_repo"]
    for item, change in zip(order.items, changes, strict=True):
        basis = IssueBasis(
            business_key=f"client-selection:{facts['payment'].payment_id}:{item.paid_item_id}",
            kind="client_referral",
            recipient_id=facts["partner"],
            paid_item_id=item.paid_item_id,
            order_id=order.order_id,
            assignment_id=None,
            referred_user_id=facts["client"],
            payment_id=facts["payment"].payment_id,
            currency="RUB",
            base_minor=1,
            rate_bps=1000,
            policy_version=version,
            snapshot_at=captured,
            registered_at=registered,
            verified_count=None,
            event_id=str(event.event_id),
            reason="confirmed_selection_capture",
            actor_id=facts["client"],
        )
        # Deliberately bypass the service to probe the SQL boundary with a
        # forged durable audit; no source facts or triggers are modified.
        async with env["container"].transaction_manager.transaction() as db:
            potential = await repo.save_potential(
                replace(basis, **change),
                "rounded_commission_zero",
                recorded_at=env["clock"].at,
                session=db,
            )
            valid = await db.scalar(
                text("""SELECT correction_zero_assessment_valid(
                :potential,:capture,:payment,:order_id,:item,:client,:gross)"""),
                dict(
                    potential=potential.assessment_id,
                    capture=event.event_id,
                    payment=facts["payment"].payment_id,
                    order_id=order.order_id,
                    item=item.paid_item_id,
                    client=facts["client"],
                    gross=1,
                ),
            )
            assert valid is (not change), change


def test_migration_freezes_current_zero_and_application_proofs():
    import importlib

    from ugc_bot.infrastructure.db.correction_approval_schema import (
        FINAL_APPLICATION_SQL,
    )

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0120_variable_tariff"
    )
    from ugc_bot.infrastructure.db.zero_commission_schema import (
        ZERO_ASSESSMENT_SQL,
    )

    application = FINAL_APPLICATION_SQL.split(
        "CREATE OR REPLACE FUNCTION correction_deny_mutation", 1
    )[1]
    assert "".join(application.split()) in "".join(
        migration.UPGRADE_SQL.split()
    )
    assert "".join(ZERO_ASSESSMENT_SQL.split()) in "".join(
        migration.UPGRADE_SQL.split()
    )
