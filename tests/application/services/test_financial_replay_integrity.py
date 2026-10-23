"""Independent monetary basis and allocation identity regression evidence."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_financial_ledger_service import (
    MemoryLedger,
    command,
)
from ugc_bot.application.financial_ports import (
    IssuedObligation,
    JournalMovement,
    ObligationBasis,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
    replay_journal,
    validate_issuance,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict", ["request", "obligation", "release", "paid"]
)
async def test_allocation_identity_cannot_be_rebound(conflict: str) -> None:
    repo = MemoryLedger()
    cmd = command()
    assert cmd.recipient_id is not None
    first = await FinancialLedgerService(repo).issue(
        cmd, recorded_at=cmd.snapshot_at, session=object()
    )
    assert isinstance(first, IssuedObligation)
    second = await FinancialLedgerService(repo).issue(
        replace(cmd, business_key="second"),
        recorded_at=cmd.snapshot_at,
        session=object(),
    )
    assert isinstance(second, IssuedObligation)
    request, allocation = uuid4(), uuid4()
    available = replace(
        first.movement,
        operation_key="available",
        movement_type="transfer",
        bucket_from="pending",
        bucket_to="available",
    )
    reserve = replace(
        available,
        operation_key="reserve",
        bucket_from="available",
        bucket_to="reserved",
        amount_minor=1000,
        request_id=request,
        allocation_id=allocation,
    )
    target = replace(reserve, operation_key="rebind")
    if conflict == "obligation":
        target = replace(target, obligation_id=second.obligation_id)
    else:
        target = replace(target, request_id=uuid4())
    if conflict in ("release", "paid"):
        target = replace(
            target,
            bucket_from="reserved",
            bucket_to="paid" if conflict == "paid" else "available",
            execution_id=uuid4() if conflict == "paid" else None,
        )
    for entry in (
        available,
        replace(
            available,
            obligation_id=second.obligation_id,
            operation_key="available2",
        ),
        reserve,
        target,
    ):
        await repo.append(entry, session=object())
        await repo.apply_projection(entry, session=object())
    entries = await repo.list_for_recipient(
        cmd.recipient_id, "RUB", session=object()
    )
    replay = replay_journal(entries, currency="RUB")
    # Equation alone remains true; ownership is a separate invariant.
    assert replay.gross - replay.paid == replay.unpaid
    assert not replay.balanced
    assert any(
        e.startswith("allocation_binding_conflict:") for e in replay.errors
    )
    report = await FinancialReconciliationService(repo).reconcile(
        cmd.recipient_id, "RUB", session=object()
    )
    assert not report.differences
    with pytest.raises(ValueError, match="reconciliation_mismatch"):
        await FinancialReconciliationService(repo).require_ready(
            cmd.recipient_id, "RUB", session=object()
        )


def test_persisted_basis_coverage_is_not_inferred_from_movements() -> None:
    cmd = command()
    assert cmd.recipient_id is not None
    oid = uuid4()
    basis = ObligationBasis(oid, cmd.recipient_id, "RUB", 5000)
    assert validate_issuance(
        (), (basis,), recipient_id=cmd.recipient_id, currency="RUB"
    ) == ("issuance_cardinality:" + str(oid),)
    movement = JournalMovement(
        obligation_id=oid,
        operation_key="initial",
        event_id="captured",
        movement_type="issuance",
        amount_minor=5000,
        currency="RUB",
        effective_at=cmd.snapshot_at,
        recorded_at=cmd.snapshot_at,
        actor_id=cmd.actor_id,
        reason="test",
        bucket_to="pending",
    )
    assert not validate_issuance(
        (movement, movement),
        (basis,),
        recipient_id=cmd.recipient_id,
        currency="RUB",
    )
    assert validate_issuance(
        (movement,), (), recipient_id=cmd.recipient_id, currency="RUB"
    ) == ("unknown_obligation:" + str(oid),)
    errors = validate_issuance(
        (replace(movement, amount_minor=4000),),
        (basis,),
        recipient_id=cmd.recipient_id,
        currency="RUB",
    )
    assert errors == ("issuance_amount:" + str(oid),)


@pytest.mark.asyncio
async def test_valid_allocation_release_paid_history_and_retry() -> None:
    cmd = command()
    repo = MemoryLedger()
    issued = await FinancialLedgerService(repo).issue(
        cmd, recorded_at=cmd.snapshot_at, session=object()
    )
    assert isinstance(issued, IssuedObligation)
    available = replace(
        issued.movement,
        operation_key="available",
        movement_type="transfer",
        bucket_from="pending",
        bucket_to="available",
    )
    reserve = replace(
        available,
        operation_key="reserve",
        bucket_from="available",
        bucket_to="reserved",
        request_id=uuid4(),
        allocation_id=uuid4(),
    )
    release = replace(
        reserve,
        operation_key="release",
        bucket_from="reserved",
        bucket_to="available",
        amount_minor=1000,
    )
    paid = replace(
        reserve,
        operation_key="paid",
        bucket_from="reserved",
        bucket_to="paid",
        amount_minor=4000,
        execution_id=uuid4(),
    )
    replay = replay_journal(
        (issued.movement, available, reserve, reserve, release, paid),
        currency="RUB",
    )
    assert replay.balanced
    assert replay.paid == 4000 and replay.unpaid == 1000


@pytest.mark.asyncio
async def test_release_cannot_spend_a_future_reserve() -> None:
    cmd = command()
    repo = MemoryLedger()
    issued = await FinancialLedgerService(repo).issue(
        cmd, recorded_at=cmd.snapshot_at, session=object()
    )
    assert isinstance(issued, IssuedObligation)
    available = replace(
        issued.movement,
        operation_key="available",
        movement_type="transfer",
        bucket_from="pending",
        bucket_to="available",
    )
    reserve = replace(
        available,
        operation_key="reserve",
        bucket_from="available",
        bucket_to="reserved",
        request_id=uuid4(),
        allocation_id=uuid4(),
        amount_minor=1000,
    )
    release = replace(
        reserve,
        operation_key="release",
        bucket_from="reserved",
        bucket_to="available",
        amount_minor=2000,
    )
    later = replace(reserve, operation_key="later-reserve")
    replay = replay_journal(
        (issued.movement, available, reserve, release, later), currency="RUB"
    )
    assert reserve.request_id is not None and reserve.allocation_id is not None
    assert replay.allocations[(reserve.request_id, reserve.allocation_id)] == 0
    assert not replay.balanced
    assert "allocation_exceeds_reserved" in replay.errors


def test_unpublished_currency_cannot_rebind_an_allocation() -> None:
    cmd = command()
    with pytest.raises(ValueError, match="unpublished_currency"):
        JournalMovement(
            obligation_id=uuid4(),
            operation_key="reserve",
            event_id="reserve",
            movement_type="transfer",
            amount_minor=1000,
            currency="USD",
            effective_at=cmd.snapshot_at,
            recorded_at=cmd.snapshot_at,
            actor_id=cmd.actor_id,
            reason="test",
            bucket_from="available",
            bucket_to="reserved",
            request_id=uuid4(),
            allocation_id=uuid4(),
        )
