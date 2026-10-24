"""Immutable legacy user potentials and new named-system producer facts."""

from dataclasses import asdict, replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
    PayloadConflict,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
    _canonical,
    payload_hash,
)

__all__ = ["item_seed", "seed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "old_fields",
    [
        ("actor_kind", "system_actor"),
        ("actor_kind", "system_actor", "rate_source", "override_id"),
    ],
)
async def test_old_user_potential_replay_retains_original_fact(
    financial_pg_engine, seed, old_fields
):
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    cmd = replace(
        basis(seed), recipient_id=None, rate_bps=None, policy_version=None
    )
    details = _canonical(asdict(cmd))
    for key in old_fields:
        details.pop(key)
    saved = dict(
        id=uuid4(),
        operation_key="potential:" + cmd.business_key,
        action="potential_basis",
        scope="paid_item:" + str(cmd.paid_item_id),
        reason="recipient_unresolved_or_absent",
        actor_id=cmd.actor_id,
        actor_kind="user",
        system_actor=None,
        obligation_id=None,
        movement_id=None,
        effective_at=cmd.snapshot_at,
        recorded_at=cmd.snapshot_at,
        details=details,
    )
    saved["payload_hash"] = payload_hash(saved)
    table = Base.metadata.tables["financial_audit_events"]
    try:
        async with factory.begin() as db:
            await db.execute(insert(table).values(**saved))
        async with factory.begin() as db:
            replay = await service.issue(
                cmd, recorded_at=cmd.snapshot_at + timedelta(days=1), session=db
            )
            assert (
                replay.assessment_id == saved["id"]
                and replay.recorded_at == saved["recorded_at"]
            )
        async with factory.begin() as db:
            actual = (
                (
                    await db.execute(
                        select(table).where(table.c.id == saved["id"])
                    )
                )
                .mappings()
                .one()
            )
            assert (
                actual["details"] == details
                and actual["payload_hash"] == saved["payload_hash"]
            )
        with pytest.raises(PayloadConflict):
            async with factory.begin() as db:
                await service.issue(
                    replace(
                        cmd,
                        actor_kind="system",
                        actor_id=None,
                        system_actor="work_entitlement",
                    ),
                    recorded_at=cmd.snapshot_at,
                    session=db,
                )
        with pytest.raises(PayloadConflict):
            async with factory.begin() as db:
                await service.issue(
                    replace(cmd, reason="different actual reason"),
                    recorded_at=cmd.snapshot_at,
                    session=db,
                )
    finally:
        await engine.dispose()
