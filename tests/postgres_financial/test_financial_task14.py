"""Task 14 regressions against PostgreSQL, including full metadata."""

from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial import test_financial_items_schema as schema_tests
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.migrations.versions import (
    financial_items,
    financial_ledger,
)

pytest_plugins = ("tests.postgres_financial.test_financial_items_schema",)

TABLES = (
    "financial_policy_versions",
    "order_items",
    "item_assignments",
    "payment_item_allocations",
)


def test_full_metadata_parity(financial_pg_engine):
    def signature(conn, table):
        inspector = inspect(conn)
        return (
            sorted(
                [
                    (
                        c["name"],
                        str(c["type"]),
                        c["nullable"],
                        getattr(c["type"], "timezone", None),
                        c["default"],
                    )
                    for c in inspector.get_columns(table)
                ]
            ),
            {
                tuple(x["column_names"])
                for x in inspector.get_unique_constraints(table)
            },
            {
                (
                    tuple(x["constrained_columns"]),
                    x["referred_table"],
                    tuple(x["referred_columns"]),
                )
                for x in inspector.get_foreign_keys(table)
            },
            {
                (x["name"], x["sqltext"])
                for x in inspector.get_check_constraints(table)
            },
            {
                (
                    x["name"],
                    tuple(x["column_names"]),
                    x["unique"],
                    x["dialect_options"].get("postgresql_where"),
                )
                for x in inspector.get_indexes(table)
            },
        )

    schema = "metadata_" + uuid4().hex
    with financial_pg_engine.begin() as conn:
        tables = (*TABLES, "payments")
        expected = {t: signature(conn, t) for t in tables}
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        Base.metadata.create_all(conn)
        for table in tables:
            assert signature(conn, table) == expected[table]
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = "
                    "'payment_item_allocations'::regclass AND NOT tgisinternal"
                )
            )
            == 2
        )
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.fixture
def migration_engine(financial_pg_engine):
    # Destructive migration tests own a fresh UUID schema; never empty a shared
    # journal or disable its protections to prepare an earlier migration test.
    import os

    url = os.environ["FINANCIAL_TEST_DATABASE_URL"]
    with isolated_financial_database(
        url, target_revision="financial_ledger"
    ) as engine:
        yield engine


def test_empty_downgrade_cleans_functions_and_triggers(migration_engine):
    financial_pg_engine = migration_engine
    # Roll back DDL to preserve the shared migrated fixture.
    with financial_pg_engine.connect() as conn:
        trans = conn.begin()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                financial_ledger.downgrade()
            for table in TABLES[::-1]:
                conn.execute(text(f"TRUNCATE {table} CASCADE"))
            conn.execute(text("TRUNCATE payments CASCADE"))
            conn.execute(text("UPDATE orders SET financial_version = NULL"))
            with Operations.context(MigrationContext.configure(conn)):
                financial_items.downgrade()
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc WHERE pronamespace = "
                        "current_schema()::regnamespace AND proname LIKE "
                        "'financial_%'"
                    )
                )
                == 0
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger WHERE tgrelid = "
                        "'payments'::regclass AND tgname = "
                        "'financial_payment_immutable'"
                    )
                )
                == 0
            )
        finally:
            trans.rollback()


def test_downgrade_preserves_capture_without_items(migration_engine, request):
    financial_pg_engine = migration_engine
    schema_tests.seed.__wrapped__(financial_pg_engine, request)
    with financial_pg_engine.connect() as conn:
        trans = conn.begin()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                financial_ledger.downgrade()
            for table in TABLES[::-1]:
                conn.execute(text(f"TRUNCATE {table} CASCADE"))
            with (
                Operations.context(MigrationContext.configure(conn)),
                pytest.raises(RuntimeError, match="Financial history"),
            ):
                financial_items.downgrade()
        finally:
            trans.rollback()


@pytest.mark.parametrize(
    "field,value", [("ordinal", 2), ("paid_item_id", None)]
)
def test_captured_item_identity_is_immutable(
    financial_pg_engine, seed, field, value
):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.models import OrderItemModel

    with Session(financial_pg_engine) as session, session.begin():
        session.get(OrderItemModel, seed["item"]).captured_at = seed["now"]
    with (
        pytest.raises(IntegrityError, match="captured_item_immutable"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        setattr(
            session.get(OrderItemModel, seed["item"]),
            field,
            value or uuid4(),
        )


@pytest.mark.asyncio
async def test_typed_repositories_caller_rollback_and_races(
    financial_pg_engine, seed
):
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.models import (
        FinancialPolicyVersionModel,
        ItemAssignmentModel,
        OrderItemModel,
        PaymentItemAllocationModel,
    )
    from ugc_bot.infrastructure.db.repositories.financial_policy import (
        SqlAlchemyFinancialPolicyRepository,
    )
    from ugc_bot.infrastructure.db.repositories.item_assignments import (
        SqlAlchemyItemAssignmentRepository,
    )
    from ugc_bot.infrastructure.db.repositories.payment_allocations import (
        SqlAlchemyPaymentAllocationRepository,
    )

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    policy_repo = SqlAlchemyFinancialPolicyRepository()
    assignments = SqlAlchemyItemAssignmentRepository()
    allocations = SqlAlchemyPaymentAllocationRepository()
    try:
        async with factory() as session:
            with pytest.raises(ValueError, match="caller_transaction_required"):
                await policy_repo.get(seed["version"], session=session)
            async with session.begin():
                assert (
                    await policy_repo.get(seed["version"], session=session)
                ).version == seed["version"]
                version = str(uuid4())
                policy = FinancialPolicyVersionModel(
                    version=version,
                    approved_by=seed["user"],
                    approved_at=seed["now"],
                    effective_from=seed["now"],
                    refund_window_seconds=3600,
                    rules={"terms": "test"},
                )
                assert (
                    await policy_repo.add(policy, session=session)
                ).version == version
                await session.rollback()
            async with session.begin():
                assert await policy_repo.get(version, session=session) is None

        barrier = asyncio.Barrier(2)

        async def assign():
            async with factory.begin() as session:
                await barrier.wait()
                try:
                    return await assignments.replace(
                        paid_item_id=seed["item"],
                        expected_version=0,
                        creator_id=seed["user"],
                        manager_id=None,
                        actor_id=seed["user"],
                        reason="synthetic",
                        at=seed["now"],
                        session=session,
                    )
                except ValueError as exc:
                    return str(exc)

        results = await asyncio.gather(assign(), assign())
        assert sum(isinstance(r, ItemAssignmentModel) for r in results) == 1
        assert "assignment_version_conflict" in results
        async with factory.begin() as session:
            new = await assignments.replace(
                paid_item_id=seed["item"],
                expected_version=1,
                creator_id=seed["user"],
                manager_id=None,
                actor_id=seed["user"],
                reason="replace",
                at=seed["now"],
                session=session,
            )
            assert new.version == 2
            history = list(
                (
                    await session.scalars(
                        select(ItemAssignmentModel)
                        .where(ItemAssignmentModel.paid_item_id == seed["item"])
                        .order_by(ItemAssignmentModel.version)
                    )
                ).all()
            )
            assert [r.valid_to is None for r in history] == [False, True]
        second = uuid4()
        async with factory.begin() as session:
            session.add(
                OrderItemModel(
                    paid_item_id=second,
                    order_id=seed["order"],
                    ordinal=2,
                    currency="RUB",
                    selection_minor=50000,
                    accompaniment_minor=0,
                    policy_version=seed["version"],
                    selection_due_at=seed["now"],
                    quote_key="q",
                    quote_payload={},
                )
            )
        barrier = asyncio.Barrier(2)

        async def allocate(item):
            try:
                async with factory.begin() as session:
                    await barrier.wait()
                    return await allocations.add(
                        PaymentItemAllocationModel(
                            allocation_key=str(uuid4()),
                            payment_id=seed["payment"],
                            paid_item_id=item,
                            order_id=seed["order"],
                            component="selection",
                            amount_minor=1,
                            currency="RUB",
                        ),
                        session=session,
                    )
            except IntegrityError as exc:
                return str(exc)

        results = await asyncio.gather(allocate(seed["item"]), allocate(second))
        assert (
            sum(isinstance(r, PaymentItemAllocationModel) for r in results) == 1
        )
        assert any(
            "allocation_exceeds_capture" in r
            for r in results
            if isinstance(r, str)
        )
        winner = next(
            r for r in results if isinstance(r, PaymentItemAllocationModel)
        )
        async with factory.begin() as session:
            retry = PaymentItemAllocationModel(
                **{
                    c.name: getattr(winner, c.name)
                    for c in winner.__table__.columns
                }
            )
            assert (
                await allocations.add(retry, session=session)
            ).allocation_key == winner.allocation_key
            retry.amount_minor = 2
            with pytest.raises(
                ValueError, match="idempotency_payload_conflict"
            ):
                await allocations.add(retry, session=session)
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "seed,change",
    [
        (100000, {"amount_minor": 0}),
        (100000, {"amount_minor": -1}),
        (100000, {"amount_minor": 50001}),
        (100000, {"component": "accompaniment"}),
        (100000, {"component": "unknown"}),
        (100000, {"currency": "USD"}),
        (100000, {"order_id": "missing"}),
        (100000, {"paid_item_id": "missing"}),
        (None, {}),
    ],
    indirect=["seed"],
)
def test_allocation_strict_caps_and_scope(financial_pg_engine, seed, change):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.models import (
        PaymentItemAllocationModel,
    )

    payment = seed["payment"]
    params = dict(
        allocation_key=str(uuid4()),
        payment_id=payment,
        paid_item_id=seed["item"],
        order_id=seed["order"],
        component="selection",
        amount_minor=1,
        currency="RUB",
    )
    params.update(
        {
            k: uuid4() if v == "missing" else v
            for k, v in change.items()
            if k != "captured_minor"
        }
    )
    with (
        pytest.raises(IntegrityError),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        session.add(PaymentItemAllocationModel(**params))


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("payments", "captured_minor", "2"),
        ("payments", "captured_minor", "NULL"),
        ("payment_item_allocations", "amount_minor", "0"),
    ],
)
def test_sql_cannot_rewrite_financial_facts(
    financial_pg_engine, seed, table, field, value
):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.infrastructure.db.models import PaymentItemAllocationModel

    key = str(uuid4())
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            PaymentItemAllocationModel(
                allocation_key=key,
                payment_id=seed["payment"],
                paid_item_id=seed["item"],
                order_id=seed["order"],
                component="selection",
                amount_minor=1,
                currency="RUB",
            )
        )
    pk, identity = (
        ("payment_id", seed["payment"])
        if table == "payments"
        else ("allocation_key", key)
    )
    with pytest.raises(IntegrityError), financial_pg_engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {table} SET {field} = {value} WHERE {pk} = :id"),
            {"id": identity},
        )
    with pytest.raises(IntegrityError), financial_pg_engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {table} WHERE {pk} = :id"), {"id": identity}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["allocation", "assignment"])
async def test_direct_sql_independent_session_race(
    financial_pg_engine, seed, kind
):
    import asyncio

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.models import (
        ItemAssignmentModel,
        OrderItemModel,
        PaymentItemAllocationModel,
    )

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    second = uuid4()
    barrier = asyncio.Barrier(2)
    try:
        async with factory.begin() as session:
            session.add(
                OrderItemModel(
                    paid_item_id=second,
                    order_id=seed["order"],
                    ordinal=2,
                    currency="RUB",
                    selection_minor=50000,
                    accompaniment_minor=0,
                    policy_version=seed["version"],
                    selection_due_at=seed["now"],
                    quote_key="q",
                    quote_payload={},
                )
            )

        async def contender(index):
            try:
                async with factory.begin() as session:
                    await barrier.wait()
                    if kind == "allocation":
                        session.add(
                            PaymentItemAllocationModel(
                                allocation_key=str(uuid4()),
                                payment_id=seed["payment"],
                                paid_item_id=seed["item"]
                                if index == 1
                                else second,
                                order_id=seed["order"],
                                component="selection",
                                amount_minor=1,
                                currency="RUB",
                            )
                        )
                    else:
                        session.add(
                            ItemAssignmentModel(
                                paid_item_id=seed["item"],
                                version=index,
                                creator_id=seed["user"],
                                actor_id=seed["user"],
                                valid_from=seed["now"],
                                reason="race",
                            )
                        )
                    await session.flush()
                return "ok"
            except IntegrityError as exc:
                return str(exc)

        results = await asyncio.gather(contender(1), contender(2))
        assert results.count("ok") == 1
        expected = (
            "allocation_exceeds_capture"
            if kind == "allocation"
            else "uq_assignment_current_item"
        )
        assert any(expected in result for result in results)
    finally:
        await engine.dispose()


def test_legacy_upgrade_preserves_unconverted_money(migration_engine, request):
    financial_pg_engine = migration_engine
    seed = schema_tests.seed.__wrapped__(financial_pg_engine, request)
    with financial_pg_engine.connect() as conn:
        trans = conn.begin()
        try:
            with Operations.context(MigrationContext.configure(conn)):
                financial_ledger.downgrade()
            for table in TABLES[::-1]:
                conn.execute(text(f"TRUNCATE {table} CASCADE"))
            conn.execute(text("TRUNCATE payments CASCADE"))
            conn.execute(text("UPDATE orders SET financial_version = NULL"))
            with Operations.context(MigrationContext.configure(conn)):
                financial_items.downgrade()
            payment = uuid4()
            conn.execute(
                text(
                    "INSERT INTO "
                    "payments(payment_id,order_id,provider,status,"
                    "amount,currency,external_id) "
                    "VALUES "
                    "(:id,:order,'synthetic','paid',123.456,'RUB',:external)"
                ),
                {
                    "id": payment,
                    "order": seed["order"],
                    "external": str(payment),
                },
            )
            before = conn.execute(
                text(
                    "SELECT amount, currency, status FROM payments "
                    "WHERE payment_id=:id"
                ),
                {"id": payment},
            ).one()
            with Operations.context(MigrationContext.configure(conn)):
                financial_items.upgrade()
            after = conn.execute(
                text(
                    "SELECT amount, currency, status, captured_minor, "
                    "financial_version FROM payments WHERE payment_id=:id"
                ),
                {"id": payment},
            ).one()
            assert tuple(after[:3]) == tuple(before)
            assert (
                after.captured_minor is None and after.financial_version is None
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT financial_version FROM orders "
                        "WHERE order_id=:id"
                    ),
                    {"id": seed["order"]},
                )
                is None
            )
        finally:
            trans.rollback()
