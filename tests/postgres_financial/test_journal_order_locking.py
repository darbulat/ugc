"""Observe actual PG blockers, then assert committed history survives."""

import asyncio
from dataclasses import replace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from tests.postgres_financial.test_journal_order_migration import (
    financial_pg_engine,
)
from ugc_bot.application.financial_ports import IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.db.migrations.versions import (
    journal_append_order as revision,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["item_seed", "seed", "financial_pg_engine"]


@pytest.mark.asyncio
@pytest.mark.parametrize("competitor", ["retry", "downgrade"])
async def test_append_barrier_and_destructive_guard(
    financial_pg_engine, seed, competitor
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()
    pids = []
    task = None

    def downgrade():
        with financial_pg_engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='5s'"))
            with Operations.context(MigrationContext.configure(conn)):
                revision.downgrade()

    try:
        async with factory.begin() as session:
            issued = await FinancialLedgerService(repo).issue(
                basis(seed), recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
        movement = replace(
            issued.movement,
            operation_key="available:" + str(issued.obligation_id),
            movement_type="transfer",
            bucket_from="pending",
            bucket_to="available",
        )

        async def retry():
            async with factory.begin() as session:
                pids.append(
                    await session.scalar(text("SELECT pg_backend_pid()"))
                )
                entered.set()
                return await repo.append(movement, session=session)

        async with factory.begin() as writer:
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            first = await repo.append(movement, session=writer)
            task = asyncio.create_task(
                retry()
                if competitor == "retry"
                else asyncio.to_thread(downgrade)
            )
            if competitor == "retry":
                await entered.wait()
                assert pids[0] != writer_pid
            async with factory.begin() as observer:
                async with asyncio.timeout(5):
                    while not await observer.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                            "WHERE :writer = ANY(pg_blocking_pids(pid)))"
                        ),
                        {"writer": writer_pid},
                    ):
                        await asyncio.sleep(0.01)
            assert not task.done()
            await writer.commit()
        if competitor == "retry":
            assert await asyncio.wait_for(task, 5) == first
        else:
            with pytest.raises(RuntimeError, match="Journal history exists"):
                await asyncio.wait_for(task, 5)
        async with factory.begin() as session:
            entries = await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            )
            assert [m.operation_key for m in entries] == [
                issued.movement.operation_key,
                movement.operation_key,
            ]
            orders = (
                (
                    await session.execute(
                        text(
                            "SELECT append_order FROM financial_movements "
                            "ORDER BY append_order"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(orders) == 2 and orders[0] < orders[1]
    finally:
        if task is not None and not task.done():
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
