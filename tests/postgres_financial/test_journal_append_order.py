"""Causal replay must survive a SQL round trip, not caller clocks or UUIDs."""

from dataclasses import replace
from uuid import UUID, uuid4

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
@pytest.mark.parametrize("clock", ["equal", "backwards", "future_funding"])
async def test_equal_clock_consumption_uuid_before_reserve(
    financial_pg_engine, seed, monkeypatch, clock
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            issued = await FinancialLedgerService(repo).issue(
                basis(seed), recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
        request, allocation = uuid4(), uuid4()
        from ugc_bot.infrastructure.db.base import Base

        async with factory.begin() as session:
            await session.execute(
                Base.metadata.tables["payout_requests"]
                .insert()
                .values(request_id=request, user_id=seed["user"])
            )
        commands = [
            replace(
                issued.movement,
                operation_key="available",
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="available",
            ),
            replace(
                issued.movement,
                operation_key="reserve",
                movement_type="transfer",
                bucket_from="available",
                bucket_to="reserved",
                request_id=request,
                allocation_id=allocation,
            ),
            replace(
                issued.movement,
                operation_key="release",
                movement_type="transfer",
                bucket_from="reserved",
                bucket_to="available",
                request_id=request,
                allocation_id=allocation,
                amount_minor=1000,
            ),
            replace(
                issued.movement,
                operation_key="paid",
                movement_type="transfer",
                bucket_from="reserved",
                bucket_to="paid",
                request_id=request,
                allocation_id=allocation,
                execution_id=uuid4(),
                amount_minor=1000,
            ),
        ]
        commands = [
            replace(
                m, operation_key=m.operation_key + str(issued.obligation_id)
            )
            for m in commands
        ]
        if clock == "backwards":
            from datetime import timedelta

            commands = [
                replace(m, recorded_at=seed["now"] - timedelta(days=i + 1))
                for i, m in enumerate(commands)
            ]
        if clock == "future_funding":
            commands[1], commands[2] = commands[2], commands[1]
        # Legal generated IDs, no mutation of immutable persisted history.
        prefix = uuid4().int & ~255
        ids = iter(UUID(int=prefix + i) for i in [10, 30, 20, 15])
        monkeypatch.setattr(
            "ugc_bot.infrastructure.db.repositories.financial_ledger.uuid4",
            lambda: next(ids),
        )
        for movement in commands:
            async with factory.begin() as session:
                await repo.lock_wallets(
                    ((seed["user"], "RUB"),), session=session
                )
                await repo.append(movement, session=session)
                if clock != "future_funding":
                    await repo.apply_projection(movement, session=session)
        if clock == "future_funding":
            async with factory.begin() as session:
                wallet = Base.metadata.tables["financial_wallets"]
                await session.execute(
                    wallet.update()
                    .where(wallet.c.recipient_id == seed["user"])
                    .values(
                        pending_minor=0,
                        available_minor=1000,
                        reserved_minor=3000,
                        paid_minor=1000,
                    )
                )
            with pytest.raises(ValueError, match="reconciliation_mismatch"):
                async with factory.begin() as session:
                    await FinancialReconciliationService(repo).require_ready(
                        seed["user"], "RUB", session=session
                    )
            return
        async with factory.begin() as session:
            report = await FinancialReconciliationService(repo).require_ready(
                seed["user"], "RUB", session=session
            )
            assert report.payout_ready
            assert report.replay.balances["reserved"] == 3000
    finally:
        await engine.dispose()
