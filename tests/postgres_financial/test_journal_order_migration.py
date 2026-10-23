"""Real transactional migration guards, including a committed old journal."""

from dataclasses import asdict
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
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
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.migrations.versions import (
    journal_append_order as revision,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
    payload_hash,
)

__all__ = ["item_seed", "seed"]


@pytest.fixture
def financial_pg_engine():
    import os

    from tests.helpers.financial_environment import isolated_financial_database

    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"]
    ) as engine:
        yield engine


@pytest.mark.asyncio
@pytest.mark.parametrize("old", [False, True])
async def test_order_migration_cycle_nonempty_refusal(
    financial_pg_engine, seed, old
):
    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # Obtain a legitimate record, then rollback; no immutable row rewritten.
        async with factory.begin() as session:
            issued = await FinancialLedgerService(repo).issue(
                basis(seed), recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            await session.rollback()
        with (
            financial_pg_engine.begin() as conn,
            Operations.context(MigrationContext.configure(conn)),
        ):
            revision.downgrade()
            revision.upgrade()
            revision.downgrade()
            if not old:
                revision.upgrade()
        async with factory.begin() as session:
            await repo.lock_wallets(((seed["user"], "RUB"),), session=session)
            await repo.save_issue(issued, session=session)
            if old:
                data = asdict(issued.movement)
                data["id"] = uuid4()
                data["payload_hash"] = payload_hash(data)
                # Core INSERT omits the new column on the actual old schema.
                await session.execute(
                    Base.metadata.tables["financial_movements"]
                    .insert()
                    .values(**data)
                )
            else:
                await repo.append(issued.movement, session=session)
        with (
            pytest.raises(RuntimeError, match="Journal history exists"),
            financial_pg_engine.begin() as conn,
            Operations.context(MigrationContext.configure(conn)),
        ):
            (revision.upgrade if old else revision.downgrade)()
        with financial_pg_engine.connect() as conn:
            assert (
                conn.scalar(text("SELECT count(*) FROM financial_movements"))
                == 1
            )
            columns = (
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=current_schema() "
                        "AND table_name='financial_movements'"
                    )
                )
                .scalars()
                .all()
            )
            assert ("append_order" in columns) is not old
    finally:
        await engine.dispose()
