"""Task 14 rollback must not erase history committed by an actual writer."""

import importlib.util
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests.helpers.financial_environment import isolated_financial_database
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import OrderModel, PaymentModel, UserModel


@pytest.fixture
def items_revision_engine(financial_pg_engine):
    # Use the original validated URL, not its search_path-bearing derivative.
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="financial_items",
    ) as engine:
        with engine.connect() as conn:
            assert conn.scalar(
                text("SELECT version_num FROM alembic_version")
            ) == ("financial_items")
            assert "rate_snapshots" not in inspect(conn).get_table_names()
        yield engine


@pytest.mark.parametrize(
    "history", ["policy", "captured_minor", "payment_version", "order_version"]
)
def test_items_downgrade_refuses_history_committed_while_waiting(
    items_revision_engine, history
):
    engine = items_revision_engine
    user, order, payment = (uuid4() for _ in range(3))
    version = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            UserModel(
                user_id=user,
                messenger_type=MessengerType.TELEGRAM,
                username="synthetic",
                status=UserStatus.ACTIVE,
            )
        )
        session.flush()
        session.add(
            OrderModel(
                order_id=order,
                advertiser_id=user,
                product_link="synthetic",
                offer_text="synthetic",
                price=1,
                bloggers_needed=1,
                status=OrderStatus.NEW,
            )
        )
        session.flush()
        session.add(
            PaymentModel(
                payment_id=payment,
                order_id=order,
                provider="synthetic",
                status=PaymentStatus.PAID,
                amount=1,
                currency="RUB",
                external_id=str(payment),
            )
        )

    pids = Queue()

    def downgrade():
        path = (
            Path(__file__).parents[2]
            / "src/ugc_bot/infrastructure/db/migrations/versions"
            / "financial_items.py"
        )
        spec = importlib.util.spec_from_file_location("items_race", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
            module.op = Operations(MigrationContext.configure(conn))
            module.downgrade()

    now = datetime.now(timezone.utc)
    changes = {
        "policy": (
            "INSERT INTO financial_policy_versions "
            "(version, approved_by, approved_at, effective_from, "
            "refund_window_seconds, rules) "
            "VALUES (:version, :user, :now, :now, 3600, '{}')",
            "SELECT version FROM financial_policy_versions "
            "WHERE version=:version",
            version,
        ),
        "captured_minor": (
            "UPDATE payments SET captured_minor=100 WHERE payment_id=:payment",
            "SELECT captured_minor FROM payments WHERE payment_id=:payment",
            100,
        ),
        "payment_version": (
            "UPDATE payments SET financial_version=:version "
            "WHERE payment_id=:payment",
            "SELECT financial_version FROM payments WHERE payment_id=:payment",
            version,
        ),
        "order_version": (
            "UPDATE orders SET financial_version=:version "
            "WHERE order_id=:order",
            "SELECT financial_version FROM orders WHERE order_id=:order",
            version,
        ),
    }
    write_sql, read_sql, expected = changes[history]
    params = dict(
        user=user, order=order, payment=payment, version=version, now=now
    )
    # The third connection must not compete for the two-slot application pool.
    observer = create_engine(engine.url, poolclass=NullPool)
    try:
        with (
            engine.connect() as writer,
            observer.connect() as probe,
            ThreadPoolExecutor(1) as pool,
        ):
            tx = writer.begin()
            writer.execute(text(write_sql), params)
            writer_pid = writer.scalar(text("SELECT pg_backend_pid()"))
            job = pool.submit(downgrade)
            try:
                ddl_pid = pids.get(timeout=5)
                deadline = time.monotonic() + 4
                blocked = False
                while time.monotonic() < deadline:
                    blockers = probe.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": ddl_pid}
                    )
                    if writer_pid in blockers:
                        blocked = True
                        break
                    time.sleep(0.01)
                assert blocked, (
                    "downgrade did not wait for the independent writer; "
                    f"worker={job.exception() if job.done() else 'running'}"
                )
                tx.commit()
                with pytest.raises(
                    RuntimeError, match="Financial history exists"
                ):
                    job.result(timeout=6)
                with engine.connect() as conn:
                    assert conn.scalar(text(read_sql), params) == expected
                    assert (
                        conn.scalar(
                            text("SELECT version_num FROM alembic_version")
                        )
                        == "financial_items"
                    )
                    assert {
                        "financial_policy_versions",
                        "order_items",
                        "item_assignments",
                        "payment_item_allocations",
                    } <= set(inspect(conn).get_table_names())
            finally:
                if tx.is_active:
                    tx.rollback()
    finally:
        observer.dispose()
