"""A matured positive adjustment participates in the actual P01 protocol."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_manual_grant_runtime import (
    financial_pg_engine,
)
from tests.postgres_financial.test_payout_runtime import (
    capture_env,
    payout_env,
    prepare,
    result_command,
    wallet,
)
from ugc_bot.application.manual_grant_ports import ApproveManualGrant
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.container.manual_grant_factory import build_manual_grants
from ugc_bot.infrastructure.db.base import Base

__all__ = ["financial_pg_engine", "capture_env", "payout_env"]


@pytest.mark.asyncio
async def test_actual_manual_grant_can_reserve_and_settle_with_bank_proof(
    payout_env,
):
    env = payout_env
    config = env["config"]
    config.financial.superadmin_user_ids_raw = str(env["client"])
    tm = env["flow"]["container"].transaction_manager
    service, sweep = build_manual_grants(config, tm)
    service.clock = env["service"].clock
    manager = env["flow"]["manager"]
    table = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        item_id = db.scalar(
            select(table.c.paid_item_id).where(
                table.c.recipient_id == manager, table.c.kind == "management"
            )
        )
    command = ApproveManualGrant(
        actor_id=env["client"],
        operation_key="grant-for-payout:" + uuid4().hex,
        paid_item_id=item_id,
        recipient_id=manager,
        amount_minor=12345,
        currency="RUB",
        reason="Reviewed independent positive supplement",
        evidence_reference="synthetic:grant-review",
        evidence_hash="c" * 64,
    )
    async with tm.transaction() as db:
        grant = await service.approve(command, session=db)
    assert wallet(env, manager)["available_minor"] == 60000
    env["flow"]["clock"].at += timedelta(days=14)
    assert (await sweep.run_once())["matured"] == 1
    assert wallet(env, manager)["available_minor"] == 72345
    prepared = await prepare(env, amount=72345, key="request-with-manual-grant")
    assert wallet(env, manager)["reserved_minor"] == 72345
    assert wallet(env, manager)["paid_minor"] == 0
    paid = await env["execute"](result_command(env, prepared))
    assert paid["state"] == "paid"
    assert wallet(env, manager)["paid_minor"] == 72345
    assert wallet(env, manager)["reserved_minor"] == 0
    async with tm.transaction() as db:
        report = await FinancialReconciliationService(
            service.ledger.repository
        ).require_ready(manager, "RUB", session=db)
        from uuid import UUID

        assert (
            report.replay.by_obligation[UUID(grant["obligation_id"])]["paid"]
            == 12345
        )
        await env["service"].repository.require_history_authority(
            manager, session=db
        )
