"""Management N/A storage mechanics, not a public entitlement producer."""

from inspect import unwrap
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.postgres_financial.test_financial_ledger_schema import put
from ugc_bot.infrastructure.db.models import ItemAssignmentModel


def management_command(seed, assignment):
    from ugc_bot.application.financial_ports import IssueBasis

    return IssueBasis(
        business_key="management:" + str(seed["item"]),
        kind="management",
        recipient_id=seed["user"],
        referred_user_id=seed["user"],
        paid_item_id=seed["item"],
        order_id=seed["order"],
        assignment_id=assignment,
        payment_id=seed["payment"],
        currency="RUB",
        base_minor=60_000,
        rate_bps=None,
        policy_version=seed["version"],
        snapshot_at=seed["now"],
        registered_at=None,
        verified_count=None,
        event_id="management-assessed:" + str(seed["item"]),
        reason="synthetic storage only; no entitlement producer",
        actor_id=seed["user"],
    )


@pytest.mark.asyncio
async def test_management_issue_roundtrips_original_fixed_fee(
    financial_pg_engine, seed
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.application.financial_ports import IssuedObligation
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )

    assignment = uuid4()
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            ItemAssignmentModel(
                assignment_id=assignment,
                paid_item_id=seed["item"],
                version=1,
                creator_id=seed["user"],
                valid_from=seed["now"],
                reason="synthetic assessed management basis",
                actor_id=seed["user"],
            )
        )
    command = management_command(seed, assignment)
    repo = SqlAlchemyFinancialLedgerRepository()
    service = FinancialLedgerService(repo)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            result = await service.issue(
                command, recorded_at=seed["now"], session=session
            )
            assert isinstance(result, IssuedObligation)
            assert result.movement.amount_minor == 60_000
        async with factory.begin() as session:
            saved = await repo.get_issue(command.business_key, session=session)
            assert saved == result
            assert saved is not None
            assert saved.basis.rate_bps is None
            assert saved.basis.registered_at is None
            assert saved.basis.verified_count is None
            assert (
                await service.issue(
                    command, recorded_at=seed["now"], session=session
                )
                == result
            )
            projection = await repo.read_projection(
                seed["user"], "RUB", session=session
            )
            assert projection["pending"] == 60_000
            assert projection["available"] == 0
            assert projection["paid"] == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize("side", ["client", "creator"])
@pytest.mark.parametrize("field", ["registered_at", "rate_bps"])
def test_referral_snapshot_keeps_required_fields_after_management_nullability(
    financial_pg_engine, ledger_seed, side, field
):
    from sqlalchemy.exc import DBAPIError

    row: dict[str, object] = dict(ledger_seed["rate"], id=uuid4(), side=side)
    row[field] = None
    with (
        pytest.raises(DBAPIError, match="ck_snapshot_referral_fields_present"),
        financial_pg_engine.begin() as conn,
    ):
        put(conn, "rate_snapshots", row)
    with financial_pg_engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM rate_snapshots WHERE id=:id"),
                {"id": row["id"]},
            )
            == 0
        )


@pytest.mark.parametrize("amount", [1, 59_999, 60_001, 120_000])
def test_storage_rejects_nonstandard_manager_reward_without_committed_rows(
    financial_pg_engine, ledger_seed, seed, runtime_role, amount
):
    from sqlalchemy.exc import DBAPIError

    assignment = uuid4()
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            ItemAssignmentModel(
                assignment_id=assignment,
                paid_item_id=seed["item"],
                version=1,
                creator_id=seed["user"],
                valid_from=seed["now"],
                reason="synthetic standard manager storage constraint",
                actor_id=seed["user"],
            )
        )
    snapshot = dict(
        ledger_seed["rate"],
        id=uuid4(),
        assignment_id=assignment,
        side="management",
        registered_at=None,
        rate_bps=None,
        verified_count=None,
        age_rule="management",
    )
    obligation = dict(
        ledger_seed["basis"],
        id=uuid4(),
        business_key="invalid-management:" + str(uuid4()),
        kind="management",
        assignment_id=assignment,
        snapshot_id=snapshot["id"],
        base_minor=amount,
        amount_minor=amount,
    )
    rejected = None
    try:
        with financial_pg_engine.begin() as conn:
            conn.execute(text(f'SET LOCAL ROLE "{runtime_role}"'))
            put(conn, "rate_snapshots", snapshot)
            put(conn, "financial_obligations", obligation)
    except DBAPIError as error:
        rejected = error
    with financial_pg_engine.connect() as conn:
        saved = (
            conn.execute(
                text("SELECT * FROM financial_obligations WHERE id=:id"),
                {"id": obligation["id"]},
            )
            .mappings()
            .one_or_none()
        )
        saved_snapshot = conn.execute(
            text("SELECT id FROM rate_snapshots WHERE id=:id"),
            {"id": snapshot["id"]},
        ).one_or_none()
    assert saved is None, (
        f"nonstandard management amount committed: {dict(saved)}"
    )
    assert saved_snapshot is None
    assert rejected is not None
    assert "ck_management_reward_standard" in str(rejected)


def test_standard_manager_migration_refuses_old_wrong_history_without_repair(
    management_private_history,
):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from sqlalchemy.exc import DBAPIError

    engine, data, history = management_private_history
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.management_reward_std"
    )
    # Legitimately relax only this revision on an owned fresh schema, commit,
    # then preserve a structurally legal pre-rule counterexample. No triggers
    # disabled, no journal updates or automatic conversion of wrong amounts.
    with (
        engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.downgrade()
    assignment = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            ItemAssignmentModel(
                assignment_id=assignment,
                paid_item_id=data["item"],
                version=1,
                creator_id=data["user"],
                valid_from=data["now"],
                reason="synthetic pre-standard manager rule history",
                actor_id=data["user"],
            )
        )
    row = dict(
        history["rate"],
        id=uuid4(),
        assignment_id=assignment,
        side="management",
        registered_at=None,
        rate_bps=None,
        verified_count=None,
        age_rule="management",
    )
    bad = dict(
        history["basis"],
        id=uuid4(),
        business_key="old-unapproved-management",
        kind="management",
        assignment_id=assignment,
        snapshot_id=row["id"],
        base_minor=120_000,
        amount_minor=120_000,
    )
    with engine.begin() as conn:
        put(conn, "rate_snapshots", row)
        put(conn, "financial_obligations", bad)
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                text("SELECT * FROM financial_obligations WHERE id=:id"),
                {"id": bad["id"]},
            )
            .mappings()
            .one()
        )
    with (
        pytest.raises(DBAPIError, match="ck_management_reward_standard"),
        engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.upgrade()
    with engine.connect() as conn:
        after = dict(
            conn.execute(
                text("SELECT * FROM financial_obligations WHERE id=:id"),
                {"id": bad["id"]},
            )
            .mappings()
            .one()
        )
        assert before == after
        assert after["amount_minor"] == 120_000
        assert "ck_management_reward_standard" not in {
            c["name"]
            for c in inspect(conn).get_check_constraints(
                "financial_obligations"
            )
        }


pytest_plugins = ("tests.postgres_financial.test_financial_ledger_schema",)


@pytest.fixture
def management_private_history(financial_pg_engine, request):
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from tests.helpers.financial_environment import isolated_financial_database
    from tests.postgres_financial import test_financial_items_schema as items
    from tests.postgres_financial import test_financial_ledger_schema as ledger

    # Validate the original owned URL, not the routed fixture engine URL.
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"]
    ) as scoped_engine:
        engine = create_engine(scoped_engine.url, poolclass=NullPool)
        try:
            data = unwrap(items.seed)(engine, request)
            history = unwrap(ledger.ledger_seed)(engine, data)
            yield engine, data, history
        finally:
            engine.dispose()


def test_populated_nonnull_management_revision_cycle_preserves_every_column(
    management_private_history,
):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    engine, data, history = management_private_history
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.management_basis_na"
    )
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": history["rate"]["id"]},
            )
            .mappings()
            .one()
        )
    with (
        engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.downgrade()
        columns = {
            c["name"]: c for c in inspect(conn).get_columns("rate_snapshots")
        }
        assert not columns["registered_at"]["nullable"]
        assert not columns["rate_bps"]["nullable"]
    with (
        engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.upgrade()
        after = dict(
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": history["rate"]["id"]},
            )
            .mappings()
            .one()
        )
        assert before == after
        columns = {
            c["name"]: c for c in inspect(conn).get_columns("rate_snapshots")
        }
        assert columns["registered_at"]["nullable"]
        assert columns["rate_bps"]["nullable"]


def test_first_management_null_history_blocks_downgrade_after_nonowner_commit(
    management_private_history,
):
    import importlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from queue import Queue

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.postgres_financial import test_financial_ledger_schema as ledger

    engine, data, history = management_private_history
    assignment = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            ItemAssignmentModel(
                assignment_id=assignment,
                paid_item_id=data["item"],
                version=1,
                creator_id=data["user"],
                valid_from=data["now"],
                reason="synthetic first management N/A writer",
                actor_id=data["user"],
            )
        )
    row = dict(
        history["rate"],
        id=uuid4(),
        assignment_id=assignment,
        side="management",
        registered_at=None,
        rate_bps=None,
        verified_count=None,
        age_rule="management",
    )
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.management_basis_na"
    )
    pids = Queue()

    def downgrade():
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='5s'"))
            conn.execute(text("SET LOCAL statement_timeout='10s'"))
            pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()

    with (
        contextmanager(unwrap(ledger.runtime_role))(engine) as role,
        engine.connect() as writer,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        tx = writer.begin()
        future = None
        try:
            writer.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert writer.scalar(
                text(
                    "SELECT NOT rolsuper FROM pg_roles "
                    "WHERE rolname=current_user"
                )
            )
            assert writer.scalar(
                text(
                    "SELECT relowner <> (SELECT oid FROM pg_roles "
                    "WHERE rolname=current_user) FROM pg_class "
                    "WHERE oid='rate_snapshots'::regclass"
                )
            )
            assert (
                writer.scalar(
                    text(
                        "SELECT count(*) FROM rate_snapshots "
                        "WHERE registered_at IS NULL OR rate_bps IS NULL"
                    )
                )
                == 0
            )
            writer_pid = writer.scalar(text("SELECT pg_backend_pid()"))
            put(writer, "rate_snapshots", row)
            future = pool.submit(downgrade)
            ddl_pid = pids.get(timeout=5)
            assert ddl_pid != writer_pid
            deadline = time.monotonic() + 3
            with engine.connect() as observer:
                observer_pid = observer.scalar(text("SELECT pg_backend_pid()"))
                assert observer_pid not in (ddl_pid, writer_pid)
                while time.monotonic() < deadline:
                    if observer.scalar(
                        text("SELECT :writer = ANY(pg_blocking_pids(:ddl))"),
                        {"writer": writer_pid, "ddl": ddl_pid},
                    ):
                        break
                    assert not future.done()
                    time.sleep(0.01)
                else:
                    pytest.fail(
                        "DDL did not wait on the actual non-owner writer"
                    )
            tx.commit()
            with pytest.raises(
                RuntimeError,
                match="management_basis_na_history_prevents_downgrade",
            ):
                future.result(timeout=15)
        finally:
            if tx.is_active:
                tx.rollback()
            if future is not None:
                try:
                    future.result(timeout=15)
                except RuntimeError as error:
                    assert (
                        str(error)
                        == "management_basis_na_history_prevents_downgrade"
                    )
    with engine.connect() as conn:
        saved = (
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": row["id"]},
            )
            .mappings()
            .one()
        )
        assert saved["registered_at"] is None
        assert saved["rate_bps"] is None
        assert saved["payload_hash"] == row["payload_hash"]
        original = (
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": history["rate"]["id"]},
            )
            .mappings()
            .one()
        )
        assert original["payload_hash"] == history["rate"]["payload_hash"]


def test_management_snapshot_has_no_fabricated_referral_fields(
    financial_pg_engine, ledger_seed, seed
):
    assignment = uuid4()
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            ItemAssignmentModel(
                assignment_id=assignment,
                paid_item_id=seed["item"],
                version=1,
                creator_id=seed["user"],
                valid_from=seed["now"],
                reason="synthetic storage assessment, not public earning",
                actor_id=seed["user"],
            )
        )
    row = dict(
        ledger_seed["rate"],
        id=uuid4(),
        assignment_id=assignment,
        side="management",
        registered_at=None,
        age_rule="management",
        verified_count=None,
        rate_bps=None,
    )
    with financial_pg_engine.begin() as conn:
        put(conn, "rate_snapshots", row)
    with financial_pg_engine.connect() as conn:
        saved = (
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": row["id"]},
            )
            .mappings()
            .one()
        )
        assert saved["side"] == "management"
        assert saved["registered_at"] is None
        assert saved["verified_count"] is None
        assert saved["rate_bps"] is None
        assert saved["assignment_id"] == assignment

    # Nullable historical facts may not be converted to fabricated defaults.
    import importlib

    import pytest
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.management_basis_na"
    )
    with (
        pytest.raises(
            RuntimeError, match="management_basis_na_history_prevents_downgrade"
        ),
        financial_pg_engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.downgrade()
    with financial_pg_engine.connect() as conn:
        after = (
            conn.execute(
                text("SELECT * FROM rate_snapshots WHERE id=:id"),
                {"id": row["id"]},
            )
            .mappings()
            .one()
        )
        assert dict(after) == dict(saved)
