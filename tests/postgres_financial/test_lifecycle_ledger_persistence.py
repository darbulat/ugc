"""Real assignment-history and maturity/override storage guards."""

import asyncio
from dataclasses import asdict, replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text, update

from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg,
)
from tests.postgres_financial.test_collaboration_persistence import (
    command as work_command,
)
from tests.postgres_financial.test_collaboration_persistence import (
    execute as work_execute,
)
from tests.postgres_financial.test_collaboration_persistence import (
    start as start_work,
)
from ugc_bot.application.financial_ports import IssueBasis, JournalMovement
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.db.models import OrderItemModel, PaymentModel
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)

__all__ = ["collaboration_pg"]


def test_lifecycle_ledger_extension_tables_are_migrated(financial_pg_engine):
    assert {
        "financial_rate_overrides",
        "financial_active_grounds",
        "financial_obligation_maturity",
    } <= set(inspect(financial_pg_engine).get_table_names())


async def basis(pg, *, recipient=None):
    factory, _, _, clock, data = pg
    async with factory.begin() as db:
        item = await db.get(OrderItemModel, data["item"])
        payment = await db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == data["order"])
        )
    return IssueBasis(
        business_key="creator:" + str(data["item"]),
        kind="creator_referral",
        recipient_id=recipient or data["client"],
        paid_item_id=data["item"],
        order_id=data["order"],
        assignment_id=data["assignment"],
        referred_user_id=data["creator"],
        payment_id=payment.payment_id,
        currency="RUB",
        base_minor=50000,
        rate_bps=1000,
        policy_version=item.policy_version,
        snapshot_at=clock.at,
        registered_at=clock.at - timedelta(days=2),
        verified_count=0,
        event_id="capture:synthetic",
        reason="server-assessed test basis",
        actor_id=data["client"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,amount", [("creator_referral", 5000), ("management", 60000)]
)
async def test_cancelled_same_recipient_replacement_preserves_both_issues(
    collaboration_pg,
    kind,
    amount,
):
    from ugc_bot.infrastructure.db.repositories.item_assignments import (
        SqlAlchemyItemAssignmentRepository,
    )

    factory, _, _, clock, data = collaboration_pg
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    old_basis = await basis(collaboration_pg)
    if kind == "management":
        old_basis = replace(
            old_basis,
            kind=kind,
            recipient_id=data["manager"],
            base_minor=amount,
            registered_at=None,
            rate_bps=None,
            verified_count=None,
        )
    async with factory.begin() as db:
        old = await service.issue(old_basis, recorded_at=clock.at, session=db)
        source = await repo.get_entry_ref(
            old.movement.operation_key, session=db
        )
        reversal = JournalMovement(
            obligation_id=old.obligation_id,
            operation_key="cancel:" + str(data["item"]),
            event_id="approved-replacement",
            movement_type="reversal",
            amount_minor=amount,
            currency="RUB",
            effective_at=clock.at,
            recorded_at=clock.at,
            actor_id=data["client"],
            reason="client-approved replacement before completed work",
            bucket_from="pending",
            bucket_to="cancelled",
            source_entry_id=source,
        )
        await repo.append(reversal, session=db)
        await repo.apply_projection(reversal, session=db)
        replacement = await SqlAlchemyItemAssignmentRepository().replace(
            paid_item_id=data["item"],
            expected_version=1,
            creator_id=data["creator"],
            manager_id=data["manager"],
            actor_id=data["client"],
            reason="approved replacement",
            at=clock.at,
            session=db,
        )
        replacement_id = replacement.assignment_id
    next_basis = replace(
        old_basis,
        business_key="replacement:" + str(data["item"]),
        assignment_id=replacement_id,
    )
    async with factory.begin() as db:
        new = await service.issue(next_basis, recorded_at=clock.at, session=db)
        assert await repo.get_issue(old_basis.business_key, session=db) == old
        assert new.obligation_id != old.obligation_id
        wallet = await repo.read_projection(
            old_basis.recipient_id, "RUB", session=db
        )
        assert wallet["pending"] == wallet["cancelled"] == amount
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_obligations "
                    "where paid_item_id=:item"
                ),
                {"item": data["item"]},
            )
            == 2
        )


@pytest.mark.asyncio
async def test_distinct_worker_recipients_cannot_create_two_live_grounds(
    collaboration_pg,
):
    factory, _, _, clock, data = collaboration_pg
    service = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    original = await basis(collaboration_pg)
    candidates = (
        original,
        replace(
            original,
            recipient_id=data["manager"],
            business_key="other:" + str(data["item"]),
        ),
    )
    barrier = asyncio.Barrier(2)
    pids = set()

    async def issue(cmd):
        async with factory.begin() as db:
            pids.add(await db.scalar(text("select pg_backend_pid()")))
            await barrier.wait()
            return await service.issue(cmd, recorded_at=clock.at, session=db)

    results = await asyncio.gather(
        *(issue(cmd) for cmd in candidates), return_exceptions=True
    )
    assert len(pids) == 2
    assert sum(not isinstance(x, BaseException) for x in results) == 1
    failed = next(
        i for i, value in enumerate(results) if isinstance(value, BaseException)
    )
    assert str(results[failed]) in {
        "active_economic_ground_exists",
        "financial_scope_changed_retry_required",
    }
    with pytest.raises(ValueError, match="active_economic_ground_exists"):
        async with factory.begin() as db:
            await service.issue(
                candidates[failed], recorded_at=clock.at, session=db
            )
    async with factory.begin() as db:
        assert (
            await db.scalar(
                text(
                    "select count(*) from financial_obligations "
                    "where paid_item_id=:item"
                ),
                {"item": data["item"]},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_sql_maturity_requires_persisted_matching_success_and_live_state(
    collaboration_pg,
):
    from ugc_bot.infrastructure.db.collaboration_models import (
        CollaborationModel,
    )

    factory, work, _, clock, data = collaboration_pg
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    cmd = await basis(collaboration_pg)
    await start_work(collaboration_pg)
    await work_execute(
        factory,
        work,
        work_command(data, "claim", "creator", 2, evidence="proof"),
    )
    await work_execute(factory, work, work_command(data, "agree", "client", 3))
    async with factory.begin() as db:
        issued = await service.issue(cmd, recorded_at=clock.at, session=db)
        source = await db.scalar(
            text(
                "select schedule_id from financial_collaboration_schedules "
                "where assignment_id=:id"
            ),
            {"id": data["assignment"]},
        )
        fact = await service.record_maturity(
            cmd.business_key,
            source,
            producer="financial_lifecycle",
            recorded_at=clock.at,
            session=db,
        )
        hold = replace(
            issued.movement,
            operation_key="hold:" + cmd.business_key,
            movement_type="transfer",
            bucket_from="pending",
            bucket_to="hold",
        )
        await service.transfer(cmd.business_key, hold, now=clock.at, session=db)
    release = replace(
        hold,
        operation_key="release:" + cmd.business_key,
        bucket_from="hold",
        bucket_to="available",
    )
    with pytest.raises(ValueError, match="hold_not_mature"):
        async with factory.begin() as db:
            await service.transfer(
                cmd.business_key,
                release,
                now=fact.release_at - timedelta(microseconds=1),
                session=db,
            )
    async with factory.begin() as db:
        await db.execute(
            update(CollaborationModel)
            .where(CollaborationModel.assignment_id == data["assignment"])
            .values(state="disputed")
        )
    with pytest.raises(ValueError, match="maturity_source_not_eligible"):
        async with factory.begin() as db:
            await service.transfer(
                cmd.business_key, release, now=fact.release_at, session=db
            )
    async with factory.begin() as db:
        assert (
            await repo.get_issue(cmd.business_key, session=db)
        ).basis.available_at is None


@pytest.mark.asyncio
async def test_sql_override_provenance_and_maturity_rows_are_immutable(
    collaboration_pg,
):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.application.financial_ports import ApprovedRateOverride
    from ugc_bot.infrastructure.db.financial_lifecycle_models import (
        RateOverrideModel,
    )

    factory, _, _, clock, data = collaboration_pg
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    cmd = await basis(collaboration_pg)
    override = ApprovedRateOverride(
        override_id=uuid4(),
        recipient_id=cmd.recipient_id,
        side="creator",
        rate_bps=2000,
        policy_version=cmd.policy_version,
        effective_from=clock.at - timedelta(days=1),
        effective_until=clock.at + timedelta(days=1),
        approved_by=data["client"],
        approved_at=clock.at - timedelta(days=2),
        reason="synthetic approved contract",
    )
    async with factory.begin() as db:
        await db.execute(
            RateOverrideModel.__table__.insert().values(**asdict(override))
        )
        cmd = replace(
            cmd,
            rate_source="override",
            override_id=override.override_id,
            rate_bps=2000,
        )
        issued = await service.issue(cmd, recorded_at=clock.at, session=db)
        assert issued.movement.amount_minor == 10000
    async with factory.begin() as db:
        assert (await repo.get_issue(cmd.business_key, session=db)).basis == cmd
    with pytest.raises(
        IntegrityError, match="financial_lifecycle_fact_immutable"
    ):
        async with factory.begin() as db:
            await db.execute(
                update(RateOverrideModel)
                .where(RateOverrideModel.override_id == override.override_id)
                .values(rate_bps=1000)
            )


@pytest.mark.asyncio
async def test_missing_ground_projection_cannot_hide_live_immutable_journal(
    collaboration_pg,
):
    factory, _, _, clock, data = collaboration_pg
    service = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    cmd = await basis(collaboration_pg)
    async with factory.begin() as db:
        await service.issue(cmd, recorded_at=clock.at, session=db)
        await db.execute(
            text(
                "DELETE FROM financial_active_grounds WHERE paid_item_id=:item"
            ),
            {"item": data["item"]},
        )
    with pytest.raises(ValueError, match="active_economic_ground_exists"):
        async with factory.begin() as db:
            await service.issue(
                replace(
                    cmd,
                    business_key="hidden-ground",
                    recipient_id=data["manager"],
                ),
                recorded_at=clock.at,
                session=db,
            )


@pytest.mark.asyncio
async def test_real_transaction_rollback_restores_journal_wallet_and_maturity(
    collaboration_pg,
):
    factory, work, _, clock, data = collaboration_pg
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    cmd = await basis(collaboration_pg)
    await start_work(collaboration_pg)
    await work_execute(
        factory,
        work,
        work_command(data, "claim", "creator", 2, evidence="proof"),
    )
    await work_execute(factory, work, work_command(data, "agree", "client", 3))
    async with factory.begin() as db:
        source = await db.scalar(
            text(
                "SELECT schedule_id FROM financial_collaboration_schedules "
                "WHERE assignment_id=:id"
            ),
            {"id": data["assignment"]},
        )
    with pytest.raises(RuntimeError, match="late_failure"):
        async with factory.begin() as db:
            await service.issue(cmd, recorded_at=clock.at, session=db)
            await service.record_maturity(
                cmd.business_key,
                source,
                producer="financial_lifecycle",
                recorded_at=clock.at,
                session=db,
            )
            raise RuntimeError("late_failure")
    async with factory.begin() as db:
        assert await repo.get_issue(cmd.business_key, session=db) is None
        for table in (
            "financial_obligation_maturity",
            "financial_active_grounds",
        ):
            assert (
                await db.scalar(
                    text(
                        f"SELECT count(*) FROM {table} WHERE paid_item_id=:id"
                    ),
                    {"id": data["item"]},
                )
                == 0
            )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM financial_movements m "
                    "JOIN financial_obligations o ON o.id=m.obligation_id "
                    "WHERE o.paid_item_id=:id"
                ),
                {"id": data["item"]},
            )
            == 0
        )
        assert not any(
            (
                await repo.read_projection(data["client"], "RUB", session=db)
            ).values()
        )
        await service.issue(cmd, recorded_at=clock.at, session=db)
        fact = await service.record_maturity(
            cmd.business_key,
            source,
            producer="financial_lifecycle",
            recorded_at=clock.at,
            session=db,
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(
        IntegrityError, match="financial_lifecycle_fact_immutable"
    ):
        async with factory.begin() as db:
            await db.execute(
                text(
                    "UPDATE financial_obligation_maturity "
                    "SET release_at=release_at WHERE id=:id"
                ),
                {"id": fact.maturity_id},
            )
