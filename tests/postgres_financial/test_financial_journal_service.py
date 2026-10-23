"""Service atomicity and independent sessions against migrated private PG."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial import test_financial_items_schema as schema_tests
from ugc_bot.application.financial_ports import IssueBasis, IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
    PayloadConflict,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import ItemAssignmentModel, UserModel
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

item_seed = schema_tests.seed


@pytest.fixture
def seed(financial_pg_engine, item_seed):
    result = item_seed
    referred = uuid4()
    with (
        Session(financial_pg_engine) as sync_session,
        sync_session.begin(),
    ):
        sync_session.add(
            UserModel(
                user_id=referred,
                messenger_type=MessengerType.TELEGRAM,
                username="referred-test",
                status=UserStatus.ACTIVE,
            )
        )
    return result | {"referred": referred}


def basis(seed):
    return IssueBasis(
        business_key="client:" + str(seed["item"]),
        kind="client_referral",
        recipient_id=seed["user"],
        referred_user_id=seed["referred"],
        paid_item_id=seed["item"],
        order_id=seed["order"],
        assignment_id=None,
        payment_id=seed["payment"],
        currency="RUB",
        base_minor=50000,
        rate_bps=1000,
        policy_version=seed["version"],
        snapshot_at=seed["now"],
        registered_at=seed["now"] - timedelta(days=2),
        verified_count=0,
        event_id="capture:test",
        reason="assessed basis test",
        actor_id=seed["user"],
        available_at=seed["now"] + timedelta(days=15),
    )


@pytest.mark.asyncio
async def test_client_grade_not_applicable_round_trips_without_zero(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = replace(basis(seed), verified_count=None)
    try:
        async with factory.begin() as session:
            original = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
        async with factory.begin() as session:
            saved = await repo.get_issue(cmd.business_key, session=session)
            assert saved == original
            assert saved is not None
            assert saved.basis.verified_count is None
            again = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            assert again == original
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["pending"] == 5000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_concurrent_retry_original_records_and_rollback(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    barrier = asyncio.Barrier(2)

    async def issue(delta):
        async with factory.begin() as session:
            await barrier.wait()
            return await service.issue(
                cmd,
                recorded_at=seed["now"] + timedelta(seconds=delta),
                session=session,
            )

    try:
        with pytest.raises(RuntimeError, match="caller abort"):
            async with factory.begin() as session:
                await service.issue(
                    cmd, recorded_at=seed["now"], session=session
                )
                raise RuntimeError("caller abort")
        async with factory.begin() as session:
            assert (
                await repo.get_issue(cmd.business_key, session=session) is None
            )
            assert (
                await repo.list_for_recipient(
                    seed["user"], "RUB", session=session
                )
                == ()
            )
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["pending"] == 0
        first, retry = await asyncio.gather(issue(0), issue(1))
        assert first == retry
        assert isinstance(first, IssuedObligation)
        async with factory.begin() as session:
            assert (
                await repo.get_issue(cmd.business_key, session=session) == first
            )
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["pending"] == 5000
            movements = await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            )
            assert movements == (first.movement,)
            with pytest.raises(PayloadConflict) as error:
                await service.issue(
                    replace(cmd, base_minor=40000),
                    recorded_at=seed["now"],
                    session=session,
                )
            assert error.value.audit_required
        async with factory.begin() as session:
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["pending"] == 5000
            table = Base.metadata.tables["financial_obligations"]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.recipient_id == seed["user"])
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_person_two_sides_and_durable_unknown(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cmd = basis(seed)
    assignment = uuid4()
    with (
        Session(financial_pg_engine) as sync_session,
        sync_session.begin(),
    ):
        sync_session.add(
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
    try:
        async with factory.begin() as session:
            unknown = replace(
                cmd, recipient_id=None, rate_bps=None, policy_version=None
            )
            potential = await service.issue(
                unknown, recorded_at=seed["now"], session=session
            )
            assert not await repo.list_for_recipient(
                seed["user"], "RUB", session=session
            )
        async with factory.begin() as session:
            retry = await service.issue(
                unknown,
                recorded_at=seed["now"] + timedelta(days=1),
                session=session,
            )
            assert retry == potential
            first = await service.issue(
                cmd, recorded_at=seed["now"], session=session
            )
            creator = replace(
                cmd,
                kind="creator_referral",
                assignment_id=assignment,
                business_key="creator:" + str(seed["item"]),
            )
            second = await service.issue(
                creator, recorded_at=seed["now"], session=session
            )
            assert isinstance(first, IssuedObligation) and isinstance(
                second, IssuedObligation
            )
            assert first.obligation_id != second.obligation_id
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["pending"] == 10000
        async with factory.begin() as session:
            assert (
                await service.issue(
                    creator,
                    recorded_at=seed["now"] + timedelta(days=1),
                    session=session,
                )
                == second
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_transfer_two_sessions_and_corrupt_projection_dry_run(
    financial_pg_engine, seed
):
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    check = FinancialReconciliationService(repo)
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
        barrier = asyncio.Barrier(2)

        async def transfer(delta):
            async with factory.begin() as session:
                await barrier.wait()
                return await service.transfer(
                    cmd.business_key,
                    replace(
                        hold, recorded_at=seed["now"] + timedelta(seconds=delta)
                    ),
                    now=seed["now"],
                    session=session,
                )

        first, retry = await asyncio.gather(transfer(0), transfer(1))
        assert first == retry
        release = replace(
            hold,
            operation_key="release:" + cmd.business_key,
            bucket_from="hold",
            bucket_to="available",
        )
        # A dispute holds the shared mutex; concurrent release must re-read it.
        async with factory.begin() as owner:
            block = replace(
                hold,
                operation_key="block:" + cmd.business_key,
                bucket_from="hold",
                bucket_to="blocked",
                amount_minor=1000,
                case_id=uuid4(),
            )
            await service.transfer(
                cmd.business_key, block, now=cmd.available_at, session=owner
            )
            entered = asyncio.Event()

            async def release_other():
                async with factory.begin() as session:
                    entered.set()
                    with pytest.raises(ValueError, match="obligation_blocked"):
                        await service.transfer(
                            cmd.business_key,
                            replace(release, amount_minor=4000),
                            now=cmd.available_at,
                            session=session,
                        )

            waiter = asyncio.create_task(release_other())
            await entered.wait()
            await owner.commit()
            await asyncio.wait_for(waiter, 5)
        async with factory.begin() as session:
            report = await check.reconcile(seed["user"], "RUB", session=session)
            assert report.payout_ready
            assert report.replay.gross == 5000
            assert report.replay.balances["hold"] == 4000
            assert report.replay.balances["blocked"] == 1000
            assert report.replay.referenced_events[-1].case_id == block.case_id
            assert (
                len(
                    await repo.list_for_recipient(
                        seed["user"], "RUB", session=session
                    )
                )
                == 3
            )
        # Independent session deliberately corrupts ONLY the mutable projection.
        async with factory.begin() as corruptor:
            wallet = Base.metadata.tables["financial_wallets"]
            await corruptor.execute(
                wallet.update()
                .where(wallet.c.recipient_id == seed["user"])
                .values(hold_minor=3999)
            )
        async with factory.begin() as session:
            report = await check.reconcile(seed["user"], "RUB", session=session)
            assert report.differences == {"hold": (4000, 3999)}
            assert report.audit_required and not report.payout_ready
            with pytest.raises(ValueError, match="reconciliation_mismatch"):
                await check.require_ready(seed["user"], "RUB", session=session)
        async with factory.begin() as session:
            assert (
                await repo.read_projection(seed["user"], "RUB", session=session)
            )["hold"] == 3999
            assert (
                len(
                    await repo.list_for_recipient(
                        seed["user"], "RUB", session=session
                    )
                )
                == 3
            )
    finally:
        await engine.dispose()
