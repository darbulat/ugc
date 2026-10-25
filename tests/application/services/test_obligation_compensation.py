from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_financial_ledger_service import command
from tests.application.services.test_lifecycle_ledger_extensions import setup
from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)


async def original(repo, ledger, bucket, amount=5000):
    basis = command()
    async with repo.transaction() as session:
        issue = await ledger.issue(
            basis, recorded_at=basis.snapshot_at, session=session
        )
        if bucket != "pending":
            # Establish real journal history through a reserve/payment, never
            # fabricate projection balances in this test fixture.
            request, allocation, execution = uuid4(), uuid4(), uuid4()
            steps = [("pending", "hold"), ("hold", "available")]
            if bucket in ("reserved", "paid"):
                steps.append(("available", "reserved"))
            if bucket == "paid":
                steps.append(("reserved", "paid"))
            for before, after in steps:
                movement = JournalMovement(
                    obligation_id=issue.obligation_id,
                    operation_key=f"fixture:{after}",
                    event_id="synthetic-payout",
                    movement_type="transfer",
                    amount_minor=amount,
                    currency="RUB",
                    effective_at=basis.available_at,
                    recorded_at=basis.available_at,
                    actor_id=basis.actor_id,
                    reason="synthetic test payout",
                    bucket_from=before,
                    bucket_to=after,
                    request_id=request
                    if after in ("reserved", "paid")
                    else None,
                    allocation_id=allocation
                    if after in ("reserved", "paid")
                    else None,
                    execution_id=execution if after == "paid" else None,
                )
                await repo.append(movement, session=session)
                await repo.apply_projection(movement, session=session)
    return issue


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket", ["pending", "available", "paid"])
async def test_cumulative_correction_preserves_paid_and_reconciles(bucket):
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )

    repo, ledger, _, _ = setup()
    issue = await original(repo, ledger, bucket)
    at = issue.basis.available_at + timedelta(days=1)
    async with repo.transaction() as session:
        movements = await ObligationCompensationService(ledger).cancel(
            issue,
            target_minor=2500,
            already_cancelled_minor=0,
            case_id=uuid4(),
            refund_id=uuid4(),
            actor_id=issue.basis.actor_id,
            now=at,
            session=session,
        )
        report = await FinancialReconciliationService(repo).require_ready(
            issue.basis.recipient_id, "RUB", session=session
        )
    assert len(movements) == 1
    assert report.replay.by_obligation[issue.obligation_id]["paid"] == (
        5000 if bucket == "paid" else 0
    )
    assert report.replay.by_obligation[issue.obligation_id]["debt"] == (
        2500 if bucket == "paid" else 0
    )
    assert report.replay.balanced


@pytest.mark.asyncio
async def test_reserved_money_requires_review_and_writes_nothing():
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )

    repo, ledger, _, _ = setup()
    issue = await original(repo, ledger, "reserved")
    before = len(repo.movements)
    with pytest.raises(ValueError, match="reserved"):
        async with repo.transaction() as session:
            await ObligationCompensationService(ledger).cancel(
                issue,
                target_minor=5000,
                already_cancelled_minor=0,
                case_id=uuid4(),
                refund_id=uuid4(),
                actor_id=issue.basis.actor_id,
                now=issue.basis.available_at,
                session=session,
            )
    assert len(repo.movements) == before


@pytest.mark.asyncio
async def test_caller_cannot_hide_previous_cancellation_or_exceed_original():
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )

    repo, ledger, _, _ = setup()
    issue = await original(repo, ledger, "pending")
    async with repo.transaction() as session:
        helper = ObligationCompensationService(ledger)
        arguments = dict(
            case_id=uuid4(),
            refund_id=uuid4(),
            actor_id=issue.basis.actor_id,
            now=issue.basis.available_at,
            session=session,
        )
        await helper.cancel(
            issue, target_minor=2500, already_cancelled_minor=0, **arguments
        )
        with pytest.raises(ValueError, match="prior"):
            await helper.cancel(
                issue, target_minor=5000, already_cancelled_minor=0, **arguments
            )
        with pytest.raises(ValueError, match="target"):
            await helper.cancel(
                issue,
                target_minor=5001,
                already_cancelled_minor=2500,
                **arguments,
            )
        assert (
            await helper.cancel(
                issue,
                target_minor=2500,
                already_cancelled_minor=2500,
                **arguments,
            )
            == ()
        )
