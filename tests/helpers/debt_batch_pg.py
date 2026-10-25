"""Two actual paid grounds fund one synthetic case; no fixture balance edits."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_payout_runtime import prepare, result_command
from ugc_bot.application.debt_recovery_ports import RecordDebtRepayment
from ugc_bot.application.manual_grant_ports import ApproveManualGrant
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.container.debt_recovery_factory import build_debt_recovery
from ugc_bot.container.manual_grant_factory import build_manual_grants
from ugc_bot.infrastructure.db.base import Base


async def paid_batch_case(env):
    """Actual management60000 + reviewed manual12345 → paid72345, debt35000."""
    tm = env["flow"]["container"].transaction_manager
    config = env["config"]
    config.financial.superadmin_user_ids_raw = str(env["client"])
    grants, _ = build_manual_grants(config, tm)
    grants.clock = env["service"].clock
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        manager = dict(
            db.execute(
                select(obligations).where(
                    obligations.c.recipient_id == env["flow"]["manager"],
                    obligations.c.kind == "management",
                )
            )
            .mappings()
            .one()
        )
    async with tm.transaction() as db:
        grant = await grants.approve(
            ApproveManualGrant(
                actor_id=env["client"],
                operation_key="batch-grant:" + uuid4().hex,
                paid_item_id=manager["paid_item_id"],
                recipient_id=env["flow"]["manager"],
                amount_minor=12345,
                currency="RUB",
                reason="Synthetic reviewed batch fixture",
                evidence_reference="synthetic:not-a-real-grant",
                evidence_hash="d" * 64,
            ),
            session=db,
        )
    env["flow"]["clock"].at += timedelta(days=14)
    async with tm.transaction() as db:
        from uuid import UUID

        assert (await grants.mature(UUID(grant["grant_id"]), session=db))[
            "mature"
        ]
    state = await prepare(env, amount=72345, key="batch-payout:" + uuid4().hex)
    assert (await env["execute"](result_command(env, state)))["state"] == "paid"
    recovery = build_debt_recovery(config)
    recovery.clock = env["service"].clock
    recovery.physical_proofs.clock = recovery.clock
    case = uuid4()
    keys = (manager["business_key"], "manual-grant:" + grant["grant_id"])
    async with tm.transaction() as db:
        ledger = recovery.ledger.repository
        await ledger.lock_recipients(
            tuple(sorted({env["client"], env["flow"]["manager"]}, key=str)),
            session=db,
        )
        for key, target in zip(keys, (30000, 5000), strict=True):
            issue = await ledger.get_issue(key, session=db)
            await ObligationCompensationService(recovery.ledger).cancel(
                issue,
                target_minor=target,
                already_cancelled_minor=0,
                case_id=case,
                refund_id=uuid4(),
                actor_id=env["client"],
                now=recovery.clock.now(),
                session=db,
            )
    observation = RecordDebtRepayment(
        actor_id=env["client"],
        operation_key="batch-incoming:" + uuid4().hex,
        recipient_id=env["flow"]["manager"],
        case_id=case,
        amount_minor=34000,
        currency="RUB",
        bank_account_label="synthetic-origin-account",
        bank_reference="synthetic-batch-repayment:" + uuid4().hex,
        occurred_at=recovery.clock.now(),
        reason="Synthetic one incoming for two grounds",
        evidence_reference="synthetic:not-real-bank-repayment",
        evidence_hash="e" * 64,
    )

    async def execute(command):
        async with tm.transaction() as db:
            method = (
                recovery.observe
                if isinstance(command, RecordDebtRepayment)
                else recovery.apply
            )
            return await method(command, session=db)

    return dict(
        service=recovery,
        execute=execute,
        observation=observation,
        business_key=keys[0],
        business_keys=keys,
        case_id=case,
        expected_debt_minor=35000,
        transactions=tm,
        paid_minor=72345,
    )
