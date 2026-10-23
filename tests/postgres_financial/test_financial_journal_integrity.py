"""Persisted integrity via legal append-only repository writes."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.financial_ports import IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["item_seed", "seed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["duplicate", "missing", "wrong_amount"])
async def test_authoritative_issuance_gate(financial_pg_engine, seed, damage):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    try:
        async with factory.begin() as session:
            if damage == "duplicate":
                issued = await FinancialLedgerService(repo).issue(
                    cmd, recorded_at=seed["now"], session=session
                )
                assert isinstance(issued, IssuedObligation)
                extra = replace(issued.movement, operation_key="extra-issuance")
                await repo.append(extra, session=session)
                await repo.apply_projection(extra, session=session)
            else:
                # Persist the authoritative basis without its initial movement.
                from ugc_bot.application.financial_ports import JournalMovement

                movement = JournalMovement(
                    obligation_id=uuid4(),
                    operation_key="issue:" + cmd.business_key,
                    event_id=cmd.event_id,
                    movement_type="issuance",
                    amount_minor=5000,
                    currency="RUB",
                    effective_at=seed["now"],
                    recorded_at=seed["now"],
                    actor_id=cmd.actor_id,
                    reason=cmd.reason,
                    bucket_to="pending",
                )
                await repo.lock_wallets(
                    ((seed["user"], "RUB"),), session=session
                )
                await repo.save_issue(
                    IssuedObligation(
                        movement.obligation_id, uuid4(), cmd, movement
                    ),
                    session=session,
                )
                if damage == "wrong_amount":
                    wrong = replace(movement, amount_minor=4000)
                    await repo.append(wrong, session=session)
                    await repo.apply_projection(wrong, session=session)
        check = FinancialReconciliationService(repo)
        # Failure escapes the caller transaction; no implicit service commit.
        with pytest.raises(ValueError, match="reconciliation_mismatch"):
            async with factory.begin() as session:
                report = await check.reconcile(
                    seed["user"], "RUB", session=session
                )
                assert (
                    not report.differences
                )  # balanced, matching bad projection
                await check.require_ready(seed["user"], "RUB", session=session)
        async with factory.begin() as session:
            entries = await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            )
            assert (
                len(entries)
                == {"duplicate": 2, "missing": 0, "wrong_amount": 1}[damage]
            )
            report = await check.reconcile(seed["user"], "RUB", session=session)
            assert report.audit_required
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_waits_for_shared_wallet_writer(
    financial_pg_engine, seed
):
    import asyncio

    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()

    async def reader():
        async with factory.begin() as session:
            entered.set()
            return await FinancialReconciliationService(repo).require_ready(
                seed["user"], "RUB", session=session
            )

    task = None
    try:
        async with factory.begin() as writer:
            issued = await FinancialLedgerService(repo).issue(
                basis(seed), recorded_at=seed["now"], session=writer
            )
            assert isinstance(issued, IssuedObligation)
            task = asyncio.create_task(reader())
            await entered.wait()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), 0.1)
            await writer.commit()
        report = await asyncio.wait_for(task, 5)
        assert report.payout_ready and report.replay.gross == 5000
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
