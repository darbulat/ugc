"""Real admin authority, temporal uniqueness, races and immutable audit."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg,
)

__all__ = ["collaboration_pg"]

from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)

START = datetime(2026, 10, 23, tzinfo=timezone.utc)


class Clock:
    at = START

    def now(self):
        return self.at


@pytest_asyncio.fixture
async def override_pg(financial_pg_engine):
    from ugc_bot.application.services.rate_override_service import (
        RateOverrideService,
    )
    from ugc_bot.infrastructure.db.repositories.rate_overrides import (
        SqlAlchemyRateOverrideRepository,
    )

    engine = create_async_engine(financial_pg_engine.url, pool_size=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    data = {key: uuid4() for key in ("admin", "other", "recipient")}
    data["policy"] = str(uuid4())
    async with factory.begin() as db:
        db.add_all(
            [
                UserModel(
                    user_id=uid,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                    admin=key != "recipient",
                )
                for key, uid in data.items()
                if key != "policy"
            ]
        )
        await db.flush()
        db.add(
            FinancialPolicyVersionModel(
                version=data["policy"],
                approved_by=data["admin"],
                approved_at=START - timedelta(days=2),
                effective_from=START - timedelta(days=1),
                refund_window_seconds=3600,
                rules={},
            )
        )
    clock = Clock()
    repo = SqlAlchemyRateOverrideRepository()
    yield factory, repo, RateOverrideService(repo, clock), clock, data
    await engine.dispose()


def command(data, **changes):
    from ugc_bot.application.override_ports import CreateRateOverride

    return CreateRateOverride(
        **(
            dict(
                operation_key="create:" + str(data["recipient"]),
                actor_id=data["admin"],
                recipient_id=data["recipient"],
                side="creator",
                policy_version=data["policy"],
                rate_bps=2000,
                effective_from=START + timedelta(days=1),
                effective_until=START + timedelta(days=30),
                reason="synthetic admin agreement",
            )
            | changes
        )
    )


def test_override_command_schema_is_migrated(financial_pg_engine):
    assert {"financial_override_commands", "financial_override_events"} <= set(
        inspect(financial_pg_engine).get_table_names()
    )


@pytest.mark.asyncio
async def test_pg_replay_and_future_revocation_preserve_old_payment(
    override_pg,
):
    from ugc_bot.application.override_ports import RevokeRateOverride
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )

    factory, repo, service, clock, data = override_pg
    cmd = command(data)
    async with factory.begin() as db:
        created = await service.execute(cmd, session=db)
    clock.at += timedelta(days=3)
    async with factory.begin() as db:
        assert await service.execute(cmd, session=db) == created
        revoke = RevokeRateOverride(
            operation_key="revoke:" + str(data["recipient"]),
            actor_id=data["other"],
            recipient_id=data["recipient"],
            side="creator",
            policy_version=data["policy"],
            override_id=created.override.approval.override_id,
            expected_version=1,
            effective_at=START + timedelta(days=10),
            reason="future end of agreement",
        )
        result = await service.execute(revoke, session=db)
        assert result.override.version == 2
        old = await SqlAlchemyFinancialLedgerRepository().get_rate_override(
            created.override.approval.override_id,
            as_of=START + timedelta(days=9),
            session=db,
        )
        assert old == created.override.approval
        assert (
            await SqlAlchemyFinancialLedgerRepository().get_rate_override(
                created.override.approval.override_id,
                as_of=revoke.effective_at,
                session=db,
            )
            is None
        )
        assert (
            await repo.select_effective_override(
                data["recipient"],
                "creator",
                data["policy"],
                revoke.effective_at,
                session=db,
            )
            is None
        )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.execute(replace(cmd, rate_bps=2500), session=db)


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [False, True])
async def test_pg_two_admins_serialize_overlapping_creates(
    override_pg, same_key
):
    factory, repo, service, _, data = override_pg
    barrier = asyncio.Barrier(2)
    pids = set()

    async def run(cmd):
        async with factory.begin() as db:
            pids.add(await db.scalar(text("select pg_backend_pid()")))
            await barrier.wait()
            return await service.execute(cmd, session=db)

    results = await asyncio.gather(
        run(command(data)),
        run(
            command(
                data,
                actor_id=data["other"],
                operation_key=(
                    command(data).operation_key
                    if same_key
                    else "other:" + str(data["recipient"])
                ),
            )
        ),
        return_exceptions=True,
    )
    assert len(pids) == 2
    assert sum(not isinstance(x, BaseException) for x in results) == 1
    assert str(next(x for x in results if isinstance(x, BaseException))) == (
        "idempotency_payload_conflict"
        if same_key
        else "override_period_overlaps"
    )
    async with factory.begin() as db:
        assert (
            await repo.select_effective_override(
                data["recipient"],
                "creator",
                data["policy"],
                START + timedelta(days=2),
                session=db,
            )
        ).rate_bps == 2000


@pytest.mark.asyncio
async def test_pg_supersede_rollback_and_all_audit_facts_are_immutable(
    override_pg,
):
    from ugc_bot.application.override_ports import SupersedeRateOverride

    factory, repo, service, _, data = override_pg
    cmd = command(data)
    async with factory.begin() as db:
        created = await service.execute(cmd, session=db)
    supersede = SupersedeRateOverride(
        operation_key="supersede:" + str(data["recipient"]),
        actor_id=data["other"],
        recipient_id=data["recipient"],
        side="creator",
        policy_version=data["policy"],
        override_id=created.override.approval.override_id,
        expected_version=1,
        rate_bps=2500,
        effective_from=START + timedelta(days=5),
        effective_until=START + timedelta(days=40),
        reason="new agreement",
    )
    with pytest.raises(RuntimeError, match="late_failure"):
        async with factory.begin() as db:
            await service.execute(supersede, session=db)
            raise RuntimeError("late_failure")
    async with factory.begin() as db:
        assert (
            await repo.get(created.override.approval.override_id, session=db)
        ).version == 1
        assert (
            await repo.get_command(supersede.operation_key, session=db) is None
        )
        assert (
            len(
                await repo.list_scope(
                    data["recipient"], "creator", data["policy"], session=db
                )
            )
            == 1
        )
        result = await service.execute(supersede, session=db)
        assert (
            await repo.select_effective_override(
                data["recipient"],
                "creator",
                data["policy"],
                supersede.effective_from,
                session=db,
            )
            == result.replacement.approval
        )
    for table, clause, params in [
        (
            "financial_rate_overrides",
            "override_id=:id",
            {"id": created.override.approval.override_id},
        ),
        (
            "financial_override_commands",
            "operation_key=:key",
            {"key": cmd.operation_key},
        ),
        (
            "financial_override_events",
            "operation_key=:key",
            {"key": cmd.operation_key},
        ),
    ]:
        with pytest.raises(IntegrityError, match="immutable"):
            async with factory.begin() as db:
                await db.execute(
                    text(f"DELETE FROM {table} WHERE {clause}"), params
                )


@pytest.mark.asyncio
async def test_pg_current_role_and_unknown_scope_reject_without_facts(
    override_pg,
):
    factory, repo, service, _, data = override_pg
    async with factory.begin() as db:
        with pytest.raises(ValueError, match="active_admin_required"):
            await service.execute(
                command(data, actor_id=data["recipient"]), session=db
            )
        with pytest.raises(ValueError, match="override_recipient_not_found"):
            await service.execute(
                command(data, recipient_id=uuid4()), session=db
            )
        with pytest.raises(ValueError, match="approved_policy_required"):
            await service.execute(
                command(data, policy_version="unknown"), session=db
            )
        assert (
            await repo.get_command(command(data).operation_key, session=db)
            is None
        )
    async with factory() as stale:
        cached = await stale.get(UserModel, data["admin"])
        assert cached.admin is True
        await stale.commit()
        async with factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == data["admin"])
                .values(admin=False)
            )
        async with stale.begin():
            with pytest.raises(ValueError, match="active_admin_required"):
                await service.execute(command(data), session=stale)


@pytest.mark.asyncio
async def test_pg_selector_fails_closed_on_ambiguous_legacy_approvals(
    override_pg,
):
    from dataclasses import asdict

    from ugc_bot.infrastructure.db.financial_lifecycle_models import (
        RateOverrideModel,
    )

    factory, repo, service, _, data = override_pg
    async with factory.begin() as db:
        created = await service.execute(command(data), session=db)
        bad = replace(created.override.approval, override_id=uuid4())
        await db.execute(
            RateOverrideModel.__table__.insert().values(**asdict(bad))
        )
        with pytest.raises(ValueError, match="override_approval_ambiguous"):
            await repo.select_effective_override(
                data["recipient"],
                "creator",
                data["policy"],
                START + timedelta(days=2),
                session=db,
            )


@pytest.mark.asyncio
async def test_pg_concurrent_supersede_requires_one_current_version(
    override_pg,
):
    from ugc_bot.application.override_ports import SupersedeRateOverride

    factory, repo, service, _, data = override_pg
    async with factory.begin() as db:
        first = await service.execute(command(data), session=db)
    barrier = asyncio.Barrier(2)
    pids = set()

    async def run(actor, key):
        cmd = SupersedeRateOverride(
            operation_key=key + str(data["recipient"]),
            actor_id=actor,
            recipient_id=data["recipient"],
            side="creator",
            policy_version=data["policy"],
            override_id=first.override.approval.override_id,
            expected_version=1,
            rate_bps=2500,
            effective_from=START + timedelta(days=5),
            effective_until=START + timedelta(days=40),
            reason="future replacement",
        )
        async with factory.begin() as db:
            pids.add(await db.scalar(text("select pg_backend_pid()")))
            await barrier.wait()
            return await service.execute(cmd, session=db)

    outcomes = await asyncio.gather(
        run(data["admin"], "supersede:a:"),
        run(data["other"], "supersede:b:"),
        return_exceptions=True,
    )
    assert len(pids) == 2
    assert sum(not isinstance(x, BaseException) for x in outcomes) == 1
    assert (
        str(next(x for x in outcomes if isinstance(x, BaseException)))
        == "override_version_conflict"
    )
    async with factory.begin() as db:
        assert (
            await repo.get(first.override.approval.override_id, session=db)
        ).version == 2
        assert (
            len(
                await repo.list_scope(
                    data["recipient"], "creator", data["policy"], session=db
                )
            )
            == 2
        )


@pytest.mark.asyncio
async def test_pg_repository_receipt_replay_does_not_duplicate_facts(
    override_pg,
):
    from sqlalchemy import select

    from ugc_bot.application.override_ports import OverrideEvent
    from ugc_bot.infrastructure.db.override_models import EVENTS

    factory, repo, service, _, data = override_pg
    cmd = command(data)
    async with factory.begin() as db:
        result = await service.execute(cmd, session=db)
        receipt = await repo.get_command(cmd.operation_key, session=db)
        row = (
            (
                await db.execute(
                    select(EVENTS).where(
                        EVENTS.c.operation_key == cmd.operation_key
                    )
                )
            )
            .mappings()
            .one()
        )
        event = OverrideEvent(**row)
        await repo.persist(
            receipt, (result.override.approval,), (event,), session=db
        )
        assert await repo.get_command(cmd.operation_key, session=db) == receipt
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await repo.persist(
                replace(receipt, payload_hash="0" * 64), (), (), session=db
            )
    async with factory() as db:
        with pytest.raises(ValueError, match="caller_transaction_required"):
            await repo.get(result.override.approval.override_id, session=db)


@pytest.mark.asyncio
async def test_pg_existing_money_snapshot_survives_later_override_revocation(
    collaboration_pg,
):
    from tests.postgres_financial.test_lifecycle_ledger_persistence import basis
    from ugc_bot.application.override_ports import (
        CreateRateOverride,
        RevokeRateOverride,
    )
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )
    from ugc_bot.application.services.rate_override_service import (
        RateOverrideService,
    )
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )
    from ugc_bot.infrastructure.db.repositories.rate_overrides import (
        SqlAlchemyRateOverrideRepository,
    )

    factory, _, _, clock, data = collaboration_pg
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["client"])
            .values(admin=True)
        )
    overrides = RateOverrideService(SqlAlchemyRateOverrideRepository(), clock)
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    cmd = CreateRateOverride(
        operation_key="approve:money:" + str(data["item"]),
        actor_id=data["client"],
        recipient_id=data["client"],
        side="creator",
        policy_version=(await basis(collaboration_pg)).policy_version,
        rate_bps=2000,
        effective_from=clock.at,
        effective_until=clock.at + timedelta(days=30),
        reason="synthetic explicit approved agreement",
    )
    async with factory.begin() as db:
        created = await overrides.execute(cmd, session=db)
        money_basis = replace(
            await basis(collaboration_pg),
            rate_source="override",
            override_id=created.override.approval.override_id,
            rate_bps=2000,
        )
        issued = await ledger.issue(
            money_basis, recorded_at=clock.at, session=db
        )
    clock.at += timedelta(days=1)
    revoke = RevokeRateOverride(
        operation_key="revoke:money:" + str(data["item"]),
        actor_id=data["client"],
        recipient_id=data["client"],
        side="creator",
        policy_version=money_basis.policy_version,
        override_id=created.override.approval.override_id,
        expected_version=1,
        effective_at=clock.at,
        reason="agreement ends for future captures",
    )
    async with factory.begin() as db:
        await overrides.execute(revoke, session=db)
        assert (
            await ledger.repository.get_issue(
                money_basis.business_key, session=db
            )
            == issued
        )
        assert issued.movement.amount_minor == 10000
        assert issued.basis.override_id == created.override.approval.override_id
        assert (
            await ledger.repository.get_rate_override(
                created.override.approval.override_id,
                as_of=money_basis.snapshot_at,
                session=db,
            )
            == created.override.approval
        )
        assert (
            await ledger.repository.get_rate_override(
                created.override.approval.override_id,
                as_of=clock.at,
                session=db,
            )
            is None
        )
