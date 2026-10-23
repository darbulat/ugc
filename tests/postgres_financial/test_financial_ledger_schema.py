"Task18 storage contract, exercised in genuinely migrated private PostgreSQL."

import json
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

pytest_plugins = ("tests.postgres_financial.test_financial_items_schema",)

TABLES = (
    "financial_wallets",
    "rate_snapshots",
    "financial_obligations",
    "financial_movements",
    "financial_audit_events",
)


def test_ledger_storage_exists(financial_pg_engine):
    assert set(TABLES) <= set(inspect(financial_pg_engine).get_table_names())


@pytest.fixture
def runtime_role(financial_pg_engine):
    role = "ledger_runtime_" + uuid4().hex
    with financial_pg_engine.begin() as conn:
        schema = conn.scalar(text("SELECT current_schema()"))
        conn.execute(
            text(
                (
                    f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB '
                    f"NOCREATEROLE NOINHERIT"
                )
            )
        )
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        # Deliberately excessive grants prove triggers remain a second barrier.
        conn.execute(
            text(
                (
                    f"GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON ALL "
                    f'TABLES IN SCHEMA "{schema}" TO "{role}"'
                )
            )
        )
    try:
        yield role
    finally:
        with financial_pg_engine.begin() as conn:
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE "{role}"'))


@pytest.mark.parametrize("journal", TABLES[1:])
@pytest.mark.parametrize(
    "verb",
    [
        "UPDATE financial_movements SET id=id",
        "DELETE FROM financial_movements",
        "TRUNCATE financial_movements CASCADE",
    ],
)
def test_ledger_is_append_only(
    financial_pg_engine, runtime_role, verb, ledger_seed, journal
):
    with financial_pg_engine.begin() as conn:
        assert ledger_seed["movement"]["id"]
        conn.execute(text(f'SET LOCAL ROLE "{runtime_role}"'))
        assert conn.scalar(
            text("SELECT NOT rolsuper FROM pg_roles WHERE rolname=current_user")
        )
        assert conn.scalar(
            text(
                (
                    "SELECT tableowner <> current_user FROM pg_tables WHERE "
                    "schemaname=current_schema() AND "
                    "tablename='financial_movements'"
                )
            )
        )
        with (
            pytest.raises(DBAPIError, match="financial_ledger_immutable"),
            conn.begin_nested(),
        ):
            conn.execute(text(verb.replace("financial_movements", journal)))


def put(conn, table, payload):
    conn.execute(
        text(
            (
                f"INSERT INTO {table} SELECT * FROM "
                f"jsonb_populate_record(NULL::{table}, CAST(:data AS "
                f"jsonb))"
            )
        ),
        {"data": json.dumps(payload, default=str)},
    )


@pytest.fixture
def ledger_seed(financial_pg_engine, seed):
    snapshot, obligation = uuid4(), uuid4()
    rate = dict(
        id=snapshot,
        recipient_id=seed["user"],
        referred_user_id=seed["user"],
        paid_item_id=seed["item"],
        order_id=seed["order"],
        assignment_id=None,
        payment_id=seed["payment"],
        currency="RUB",
        side="client",
        effective_at=seed["now"],
        registered_at=seed["now"],
        age_rule="first_year",
        verified_count=0,
        rate_bps=1000,
        policy_version=seed["version"],
        payload_hash="a" * 64,
    )
    basis = dict(
        id=obligation,
        business_key=str(uuid4()),
        kind="client_referral",
        recipient_id=seed["user"],
        paid_item_id=seed["item"],
        order_id=seed["order"],
        assignment_id=None,
        currency="RUB",
        base_minor=50000,
        amount_minor=5000,
        snapshot_id=snapshot,
        policy_version=seed["version"],
        hold_until=None,
        available_at=None,
        recorded_at=seed["now"],
        payload_hash="b" * 64,
    )
    movement = dict(
        id=uuid4(),
        obligation_id=obligation,
        operation_key=str(uuid4()),
        event_id="event",
        movement_type="issuance",
        amount_minor=5000,
        currency="RUB",
        effective_at=seed["now"],
        recorded_at=seed["now"],
        actor_id=seed["user"],
        actor_kind="user",
        system_actor=None,
        reason="synthetic",
        bucket_from=None,
        bucket_to="pending",
        source_entry_id=None,
        request_id=None,
        allocation_id=None,
        execution_id=None,
        refund_id=None,
        case_id=None,
        payload_hash="c" * 64,
    )
    with financial_pg_engine.begin() as conn:
        put(conn, "rate_snapshots", rate)
        put(conn, "financial_obligations", basis)
        put(conn, "financial_movements", movement)
    return dict(seed=seed, rate=rate, basis=basis, movement=movement)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": 0},
        {"amount_minor": -1},
        {"currency": "USD"},
        {"recipient_id": None},
        {"recipient_id": str(uuid4())},
        {"paid_item_id": str(uuid4())},
        {"kind": "unknown"},
        {"base_minor": 0},
    ],
)
def test_obligation_constraints(financial_pg_engine, ledger_seed, change):
    payload = (
        ledger_seed["basis"]
        | dict(id=uuid4(), business_key=str(uuid4()))
        | change
    )
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(conn, "financial_obligations", payload)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_minor": 0},
        {"currency": "USD"},
        {"obligation_id": str(uuid4())},
        {"actor_id": None},
        {"movement_type": "invented"},
        {"movement_type": "reversal"},
        {"bucket_to": "available"},
        {
            "movement_type": "transfer",
            "bucket_from": "paid",
            "bucket_to": "available",
        },
        {
            "movement_type": "transfer",
            "bucket_from": "available",
            "bucket_to": "cancelled",
        },
        {
            "movement_type": "transfer",
            "bucket_from": "available",
            "bucket_to": "paid",
            "execution_id": str(uuid4()),
        },
        {
            "movement_type": "transfer",
            "bucket_from": "available",
            "bucket_to": "reserved",
        },
    ],
)
def test_movement_sql_constraints(financial_pg_engine, ledger_seed, change):
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(
            conn,
            "financial_movements",
            ledger_seed["movement"]
            | dict(id=uuid4(), operation_key=str(uuid4()))
            | change,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"rate_bps": -1},
        {"rate_bps": 10001},
        {"verified_count": -1},
        {"side": "unknown"},
        {"currency": "USD"},
        {"age_rule": "unknown"},
    ],
)
def test_snapshot_sql_constraints(financial_pg_engine, ledger_seed, change):
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(
            conn,
            "rate_snapshots",
            ledger_seed["rate"] | dict(id=uuid4()) | change,
        )


@pytest.mark.asyncio
async def test_caller_session_repositories(financial_pg_engine, ledger_seed):
    import importlib.util

    assert (
        importlib.util.find_spec(
            "ugc_bot.infrastructure.db.repositories.financial_ledger"
        )
        is not None
    ), "caller-session ledger storage adapter missing"
    from dataclasses import replace
    from datetime import timedelta, timezone

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.application.financial_ports import JournalMovement
    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )

    repo = SqlAlchemyFinancialLedgerRepository()
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    raw = {
        k: v
        for k, v in ledger_seed["movement"].items()
        if k not in ("id", "payload_hash")
    }
    movement = JournalMovement(**(raw | dict(operation_key=str(uuid4()))))
    try:
        async with factory() as session:
            with pytest.raises(ValueError, match="caller_transaction_required"):
                await repo.append(movement, session=session)
            async with session.begin():
                first = await repo.append(movement, session=session)
                retry = replace(
                    movement,
                    recorded_at=movement.recorded_at + timedelta(days=1),
                    effective_at=movement.effective_at.astimezone(
                        timezone(timedelta(hours=3))
                    ),
                )
                assert await repo.append(retry, session=session) == first
                assert first.recorded_at == movement.recorded_at
                with pytest.raises(
                    ValueError, match="idempotency_payload_conflict"
                ):
                    await repo.append(
                        replace(movement, amount_minor=1), session=session
                    )
                assert first in await repo.list_for_recipient(
                    ledger_seed["seed"]["user"], "RUB", session=session
                )
                await session.rollback()
            async with session.begin():
                assert movement not in await repo.list_for_recipient(
                    ledger_seed["seed"]["user"], "RUB", session=session
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_storage_keys_locks_and_concurrent_retries(
    financial_pg_engine, ledger_seed
):
    import asyncio
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.repositories.financial_ledger import (
        SqlAlchemyFinancialLedgerRepository,
    )

    repo = SqlAlchemyFinancialLedgerRepository()
    assert hasattr(repo, "add_obligation"), (
        "obligation storage contract missing"
    )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user = ledger_seed["seed"]["user"]
    basis = ledger_seed["basis"] | dict(
        id=uuid4(), business_key=str(uuid4()), kind="creator"
    )
    rate = ledger_seed["rate"] | dict(id=uuid4(), side="creator")
    basis["snapshot_id"] = rate["id"]
    try:
        async with factory.begin() as session:
            await repo.lock_wallets(
                ((user, "RUB"), (user, "RUB")), session=session
            )
            first_rate = await repo.add_rate_snapshot(rate, session=session)
            assert (
                await repo.add_rate_snapshot(rate, session=session)
                == first_rate
            )
            first = await repo.add_obligation(basis, session=session)
            assert first["kind"] == "creator_referral"
            retry = basis | dict(
                id=uuid4(),
                kind="creator_referral",
                recorded_at=basis["recorded_at"] + timedelta(days=1),
            )
            assert await repo.add_obligation(retry, session=session) == first
            with pytest.raises(
                ValueError, match="idempotency_payload_conflict"
            ):
                await repo.add_obligation(
                    basis | dict(amount_minor=1), session=session
                )
            audit = dict(
                id=uuid4(),
                operation_key=str(uuid4()),
                action="synthetic",
                scope="ledger",
                reason="test",
                actor_id=None,
                actor_kind="system",
                system_actor="test-producer",
                obligation_id=first["id"],
                movement_id=None,
                effective_at=ledger_seed["seed"]["now"],
                recorded_at=ledger_seed["seed"]["now"],
                details={"ref": "protected:test"},
            )
            assert await repo.add_audit_event(
                audit, session=session
            ) == await repo.add_audit_event(
                audit
                | dict(recorded_at=audit["recorded_at"] + timedelta(days=1)),
                session=session,
            )
        # Independent transactions, same operation race must return first row.
        barrier = asyncio.Barrier(2)

        async def retry_basis():
            async with factory.begin() as session:
                await barrier.wait()
                return await repo.add_obligation(
                    basis | dict(id=uuid4()), session=session
                )

        results = await asyncio.gather(retry_basis(), retry_basis())
        assert results[0]["id"] == results[1]["id"] == first["id"]
        async with factory.begin() as owner:
            await repo.lock_recipients((user,), session=owner)
            acquired = asyncio.Event()

            async def waiter():
                async with factory.begin() as other:
                    await repo.lock_recipients((user,), session=other)
                    acquired.set()

            task = asyncio.create_task(waiter())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(acquired.wait(), 0.15)
            # FK KEY SHARE must coexist with the legacy/v1 writer mutex.
            async with factory.begin() as fk_session:
                await repo.add_rate_snapshot(
                    rate | dict(id=uuid4()), session=fk_session
                )
            await owner.commit()
            await asyncio.wait_for(task, 3)
    finally:
        await engine.dispose()


def test_downgrade_refuses_financial_history(financial_pg_engine, ledger_seed):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import financial_ledger

    with financial_pg_engine.connect() as conn:
        tx = conn.begin()
        try:
            with (
                Operations.context(MigrationContext.configure(conn)),
                pytest.raises(RuntimeError, match="Financial history"),
            ):
                financial_ledger.downgrade()
            assert (
                conn.scalar(
                    text(
                        "SELECT amount_minor FROM financial_movements "
                        "WHERE id=:id"
                    ),
                    {"id": ledger_seed["movement"]["id"]},
                )
                == 5000
            )
        finally:
            tx.rollback()


def test_snapshot_side_must_match_obligation(financial_pg_engine, ledger_seed):
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(
            conn,
            "financial_obligations",
            ledger_seed["basis"]
            | dict(
                id=uuid4(),
                business_key=str(uuid4()),
                kind="creator_referral",
            ),
        )


def test_direct_sql_keys_and_distinct_corrections(
    financial_pg_engine, ledger_seed
):
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(
            conn,
            "financial_obligations",
            ledger_seed["basis"] | dict(id=uuid4()),
        )
        with pytest.raises(DBAPIError), conn.begin_nested():
            put(
                conn,
                "financial_movements",
                ledger_seed["movement"] | dict(id=uuid4()),
            )
        for _ in range(2):
            put(
                conn,
                "financial_movements",
                ledger_seed["movement"]
                | dict(
                    id=uuid4(),
                    operation_key=str(uuid4()),
                    amount_minor=1,
                    movement_type="reversal",
                    source_entry_id=ledger_seed["movement"]["id"],
                    bucket_to="cancelled",
                ),
            )


def test_full_ledger_metadata_parity(financial_pg_engine):
    from ugc_bot.infrastructure.db.base import Base

    def signature(conn, table):
        inspector = inspect(conn)
        return (
            inspector.get_columns(table),
            inspector.get_check_constraints(table),
            inspector.get_foreign_keys(table),
            inspector.get_unique_constraints(table),
        )

    # Normalize driver type objects; identity is not a schema difference.
    def normalized(conn, table):
        return json.dumps(signature(conn, table), default=str, sort_keys=True)

    schema = "ledger_metadata_" + uuid4().hex
    with financial_pg_engine.begin() as conn:
        expected = {table: normalized(conn, table) for table in TABLES}
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        Base.metadata.create_all(conn)
        for table in TABLES:
            assert normalized(conn, table) == expected[table]
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE financial_movements SET id=id",
        "DELETE FROM financial_movements",
        "TRUNCATE financial_movements CASCADE",
        "ALTER TABLE financial_movements DISABLE TRIGGER ALL",
    ],
)
def test_runtime_least_privilege(financial_pg_engine, runtime_role, statement):
    with financial_pg_engine.begin() as conn:
        conn.execute(
            text(
                (
                    f"REVOKE UPDATE,DELETE,TRUNCATE ON financial_movements"
                    f' FROM "{runtime_role}"'
                )
            )
        )
        conn.execute(text(f'SET LOCAL ROLE "{runtime_role}"'))
        with pytest.raises(DBAPIError) as error, conn.begin_nested():
            conn.execute(text(statement))
        assert error.value.orig.sqlstate == "42501"


def test_empty_downgrade_and_legacy_money_preserved(financial_pg_engine, seed):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.migrations.versions import financial_ledger

    schema = "ledger_legacy_" + uuid4().hex
    with financial_pg_engine.begin() as conn:
        original = conn.scalar(text("SELECT current_schema()"))
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        Base.metadata.create_all(conn)
        with Operations.context(MigrationContext.configure(conn)):
            financial_ledger.downgrade()
        assert not set(TABLES) & set(inspect(conn).get_table_names())
        assert (
            conn.scalar(
                text(
                    (
                        "SELECT count(*) FROM pg_proc WHERE "
                        "pronamespace=current_schema()::regnamespace "
                        "AND proname"
                        " LIKE 'ledger_%'"
                    )
                )
            )
            == 0
        )
        for table, key in [("users", "user_id"), ("orders", "order_id")]:
            value = seed["user"] if table == "users" else seed["order"]
            conn.execute(
                text(
                    (
                        f"INSERT INTO {table} SELECT "
                        f"(jsonb_populate_record(NULL::{table},to_jsonb(src))).*"
                        f' FROM "{original}".{table} src WHERE {key}=:id'
                    )
                ),
                {"id": value},
            )
        conn.execute(
            text(
                (
                    f"INSERT INTO payments SELECT "
                    f"(jsonb_populate_record(NULL::payments,to_jsonb(p) ||"
                    " jsonb_build_object('captured_minor', NULL, "
                    "'financial_version', NULL))).*"
                    f' FROM "{original}".payments p WHERE payment_id=:id'
                )
            ),
            {"id": seed["payment"]},
        )
        before = conn.scalar(text("SELECT to_jsonb(p) FROM payments p"))
        with Operations.context(MigrationContext.configure(conn)):
            financial_ledger.upgrade()
        assert conn.scalar(text("SELECT to_jsonb(p) FROM payments p")) == before
        assert all(
            conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            for table in TABLES
        )
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.parametrize(
    "field", ["case_id", "refund_id", "allocation_id", "execution_id"]
)
def test_sql_rejects_nil_references(financial_pg_engine, ledger_seed, field):
    payload = ledger_seed["movement"] | {
        "id": uuid4(),
        "operation_key": str(uuid4()),
        field: "00000000-0000-0000-0000-000000000000",
    }
    with (
        financial_pg_engine.begin() as conn,
        pytest.raises(DBAPIError),
        conn.begin_nested(),
    ):
        put(conn, "financial_movements", payload)
