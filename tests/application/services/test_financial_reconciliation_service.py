"""Dry-run journal mathematics, not a bank confirmation path."""

import importlib
import importlib.util
from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_financial_ledger_service import (
    MemoryLedger,
    command,
)
from ugc_bot.application.financial_ports import IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)


def api():
    name = "ugc_bot.application.services.financial_reconciliation_service"
    assert importlib.util.find_spec(name) is not None, (
        "dry-run reconciliation missing"
    )
    return importlib.import_module(name)


@pytest.mark.asyncio
async def test_replay_rebuilds_allocation_and_balance():
    module = api()
    repo = MemoryLedger()
    cmd = command()
    issued = await FinancialLedgerService(repo).issue(
        cmd, recorded_at=cmd.snapshot_at, session=object()
    )
    assert isinstance(issued, IssuedObligation)
    check = module.FinancialReconciliationService(repo)
    clean = await check.reconcile(cmd.recipient_id, "RUB", session=object())
    assert clean.payout_ready
    assert (clean.replay.gross, clean.replay.unpaid, clean.replay.debt) == (
        5000,
        5000,
        0,
    )
    repo.wallet["pending"] = 4999
    bad = await check.reconcile(cmd.recipient_id, "RUB", session=object())
    assert not bad.payout_ready and bad.audit_required
    assert bad.differences["pending"] == (5000, 4999)
    assert repo.wallet["pending"] == 4999  # Never automatically repair money.
    with pytest.raises(ValueError, match="reconciliation_mismatch"):
        await check.require_ready(cmd.recipient_id, "RUB", session=object())
    # Historical DTO fixture only, not a payment command or persisted paid fact.
    original = issued.movement
    request, allocation, case = uuid4(), uuid4(), uuid4()

    def move(key, source, target):
        return replace(
            original,
            operation_key=key,
            movement_type="transfer",
            bucket_from=source,
            bucket_to=target,
            request_id=request,
            allocation_id=allocation,
            execution_id=uuid4() if target == "paid" else None,
        )

    entries = (
        original,
        move("hold", "pending", "hold"),
        move("available", "hold", "available"),
        move("reserve", "available", "reserved"),
        move("paid", "reserved", "paid"),
        replace(
            original,
            operation_key="debt",
            movement_type="debt",
            bucket_to=None,
            amount_minor=3000,
            source_entry_id=uuid4(),
            case_id=case,
        ),
        replace(
            original,
            operation_key="recovery",
            movement_type="recovery",
            bucket_to=None,
            amount_minor=1000,
            source_entry_id=uuid4(),
            case_id=case,
        ),
    )
    replay = module.replay_journal(entries, currency="RUB")
    assert (
        replay.gross,
        replay.reversed,
        replay.paid,
        replay.recovered,
        replay.unpaid,
        replay.debt,
    ) == (5000, 3000, 5000, 1000, 0, 2000)
    assert replay.balanced
    assert replay.allocations[(request, allocation)] == 0
    assert replay.allocation_paid[(request, allocation)] == 5000
    assert replay.by_obligation[issued.obligation_id]["paid"] == 5000


@pytest.mark.asyncio
async def test_replay_rejects_debt_without_paid_despite_balanced_equation():
    module = api()
    cmd = command()
    issued = await FinancialLedgerService(MemoryLedger()).issue(
        cmd, recorded_at=cmd.snapshot_at, session=object()
    )
    assert isinstance(issued, IssuedObligation)
    debt = replace(
        issued.movement,
        operation_key="bad-debt",
        movement_type="debt",
        bucket_to=None,
        source_entry_id=uuid4(),
        case_id=uuid4(),
        amount_minor=1000,
    )
    replay = module.replay_journal((issued.movement, debt), currency="RUB")
    assert not replay.balanced
    assert "debt_exceeds_historical_paid" in replay.errors
