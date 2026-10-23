"""Authorized wallet-wide transfer boundary on real PostgreSQL."""

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_financial_issue_defensive import (
    persisted_state,
)
from tests.postgres_financial.test_financial_journal_service import (
    basis,
    item_seed,
    seed,
)
from ugc_bot.application.financial_ports import IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["item_seed", "seed"]


@pytest.mark.asyncio
async def test_distinct_keys_cannot_release_duplicate_issuance_above_cap(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    assert cmd.available_at is not None
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            hold = replace(
                issued.movement,
                operation_key="hold:" + cmd.business_key,
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
            )
            await service.transfer(
                cmd.business_key, hold, now=seed["now"], session=session
            )
            extra = replace(
                issued.movement, operation_key="extra:" + cmd.business_key
            )
            await repo.append(extra, session=session)
            await repo.apply_projection(extra, session=session)
        before = persisted_state(financial_pg_engine)
        attempts = (
            replace(
                hold,
                operation_key="release:first:" + cmd.business_key,
                bucket_from="hold",
                bucket_to="available",
            ),
            replace(hold, operation_key="hold:extra:" + cmd.business_key),
            replace(
                hold,
                operation_key="release:extra:" + cmd.business_key,
                bucket_from="hold",
                bucket_to="available",
            ),
        )
        rejected = []
        for movement in attempts:
            try:
                async with factory.begin() as session:
                    await service.transfer(
                        cmd.business_key,
                        movement,
                        now=cmd.available_at,
                        session=session,
                    )
            except ValueError as error:
                assert str(error) == "reconciliation_mismatch_audit_required"
                rejected.append(movement.operation_key)
        # Observe the actual committed invariant before asserting eager refusal.
        async with factory.begin() as session:
            bases = await repo.list_obligation_bases(
                seed["user"], "RUB", session=session
            )
            cap = next(
                b.amount_minor
                for b in bases
                if b.obligation_id == issued.obligation_id
            )
            projection = await repo.read_projection(
                seed["user"], "RUB", session=session
            )
            assert cap == issued.movement.amount_minor == 5000
            assert projection["available"] <= cap
        assert rejected == [m.operation_key for m in attempts]
        assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_projection_mismatch_rejects_new_transfer_without_repair(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    assert cmd.available_at is not None
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            hold = replace(
                issued.movement,
                operation_key="hold:" + cmd.business_key,
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
            )
            # Legal journal append deliberately omits its mutable projection.
            await repo.append(hold, session=session)
        before = persisted_state(financial_pg_engine)
        with pytest.raises(
            ValueError, match="^reconciliation_mismatch_audit_required$"
        ):
            async with factory.begin() as session:
                await service.transfer(
                    cmd.business_key,
                    replace(
                        hold,
                        operation_key="release:" + cmd.business_key,
                        bucket_from="hold",
                        bucket_to="available",
                    ),
                    now=cmd.available_at,
                    session=session,
                )
        assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "missing",
        "wrong_amount",
        "other_recipient",
        "valid",
        "retry",
    ],
)
async def test_other_obligation_wallet_boundary_and_readonly_retry(
    financial_pg_engine, seed, damage
):
    from uuid import uuid4

    from ugc_bot.application.services.financial_ledger_service import (
        PayloadConflict,
    )

    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    assert cmd.available_at is not None
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
            hold = replace(
                issued.movement,
                operation_key="hold:" + cmd.business_key,
                movement_type="transfer",
                bucket_from="pending",
                bucket_to="hold",
            )
            saved = await service.transfer(
                cmd.business_key, hold, now=seed["now"], session=session
            )
            # A distinct immutable economic basis on this same paid item.
            from ugc_bot.infrastructure.db.models import ItemAssignmentModel

            assignment = uuid4()
            session.add(
                ItemAssignmentModel(
                    assignment_id=assignment,
                    paid_item_id=seed["item"],
                    version=1,
                    creator_id=seed["referred"],
                    valid_from=seed["now"],
                    reason="test assignment",
                    actor_id=seed["user"],
                )
            )
            await session.flush()
            other = replace(
                cmd,
                business_key="other:" + cmd.business_key,
                kind="creator_referral",
                assignment_id=assignment,
                recipient_id=seed["referred"]
                if damage == "other_recipient"
                else seed["user"],
                referred_user_id=seed["user"],
            )
            if damage in ("missing", "wrong_amount"):
                await repo.lock_wallets(
                    ((other.recipient_id, "RUB"),), session=session
                )
                movement = replace(
                    issued.movement,
                    obligation_id=uuid4(),
                    operation_key="issue:" + other.business_key,
                )
                await repo.save_issue(
                    IssuedObligation(
                        movement.obligation_id, uuid4(), other, movement
                    ),
                    session=session,
                )
                if damage == "wrong_amount":
                    wrong = replace(movement, amount_minor=4000)
                    await repo.append(wrong, session=session)
                    await repo.apply_projection(wrong, session=session)
            else:
                second = await service.issue(
                    other, recorded_at=seed["now"], session=session
                )
                assert isinstance(second, IssuedObligation)
                if damage != "valid":
                    extra = replace(
                        second.movement,
                        operation_key="extra:" + other.business_key,
                    )
                    await repo.append(extra, session=session)
                    await repo.apply_projection(extra, session=session)
        before = persisted_state(financial_pg_engine)
        if damage == "retry":
            async with factory.begin() as session:
                retry = await service.transfer(
                    cmd.business_key,
                    replace(hold, recorded_at=cmd.available_at),
                    now=cmd.available_at,
                    session=session,
                )
                assert retry == saved
            assert persisted_state(financial_pg_engine) == before
            with pytest.raises(PayloadConflict) as caught:
                async with factory.begin() as session:
                    await service.transfer(
                        cmd.business_key,
                        replace(hold, reason="conflicting audit reason"),
                        now=cmd.available_at,
                        session=session,
                    )
            assert caught.value.audit_required
            assert caught.value.operation_key == hold.operation_key
            assert persisted_state(financial_pg_engine) == before
        else:
            release = replace(
                hold,
                operation_key="release:" + cmd.business_key,
                bucket_from="hold",
                bucket_to="available",
            )
            if damage in ("valid", "other_recipient"):
                # Real write then caller abort: the service owns no commit.
                with pytest.raises(RuntimeError, match="caller abort"):
                    async with factory.begin() as session:
                        await service.transfer(
                            cmd.business_key,
                            release,
                            now=cmd.available_at,
                            session=session,
                        )
                        assert (
                            await repo.read_projection(
                                seed["user"], "RUB", session=session
                            )
                        )["available"] == 5000
                        raise RuntimeError("caller abort")
                assert persisted_state(financial_pg_engine) == before
                async with factory.begin() as session:
                    await service.transfer(
                        cmd.business_key,
                        release,
                        now=cmd.available_at,
                        session=session,
                    )
                async with factory.begin() as session:
                    assert (
                        await repo.read_projection(
                            seed["user"], "RUB", session=session
                        )
                    )["available"] == 5000
            else:
                with pytest.raises(
                    ValueError, match="^reconciliation_mismatch_audit_required$"
                ):
                    async with factory.begin() as session:
                        await service.transfer(
                            cmd.business_key,
                            release,
                            now=cmd.available_at,
                            session=session,
                        )
                assert persisted_state(financial_pg_engine) == before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_transfer_waits_for_corrupting_wallet_writer(
    financial_pg_engine, seed
):
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    entered = asyncio.Event()
    pids = []
    task = None
    try:
        async with factory.begin() as session:
            issued = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert isinstance(issued, IssuedObligation)
        hold = replace(
            issued.movement,
            operation_key="hold:" + cmd.business_key,
            movement_type="transfer",
            bucket_from="pending",
            bucket_to="hold",
        )

        async def transfer():
            async with factory.begin() as session:
                await session.execute(text("SET LOCAL lock_timeout='10s'"))
                pids.append(
                    await session.scalar(text("SELECT pg_backend_pid()"))
                )
                entered.set()
                await service.transfer(
                    cmd.business_key, hold, now=seed["now"], session=session
                )

        async with factory.begin() as writer:
            writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            extra = replace(
                issued.movement, operation_key="extra:" + cmd.business_key
            )
            await repo.append(extra, session=writer)
            await repo.apply_projection(extra, session=writer)
            task = asyncio.create_task(transfer())
            await entered.wait()
            assert pids[0] != writer_pid
            async with factory.begin() as observer:
                async with asyncio.timeout(5):
                    while writer_pid not in await observer.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[0]}
                    ):
                        await asyncio.sleep(0.01)
            assert not task.done()
            await writer.commit()
        before = persisted_state(financial_pg_engine)
        with pytest.raises(
            ValueError, match="^reconciliation_mismatch_audit_required$"
        ):
            await asyncio.wait_for(task, 5)
        assert persisted_state(financial_pg_engine) == before
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
