"""Rollback must serialize its empty-history check with ledger writers."""

import importlib.util
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tests.postgres_financial.test_financial_ledger_schema import put

pytest_plugins = ("tests.postgres_financial.test_financial_items_schema",)


@pytest.fixture
def observer_connection(financial_pg_engine):
    probe = create_engine(financial_pg_engine.url, poolclass=NullPool)
    try:
        with probe.connect() as conn:
            yield conn
    finally:
        probe.dispose()


def test_downgrade_refuses_history_committed_while_ddl_waits(
    financial_pg_engine, seed, observer_connection
):
    engine = financial_pg_engine
    payload = dict(
        id=uuid4(),
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
    pids = Queue()

    def downgrade():
        path = (
            Path(__file__).parents[2]
            / "src/ugc_bot/infrastructure/db/migrations/versions"
            / "financial_ledger.py"
        )
        spec = importlib.util.spec_from_file_location("ledger_race", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with engine.begin() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            pids.put(db.scalar(text("SELECT pg_backend_pid()")))
            module.op = Operations(MigrationContext.configure(db))
            module.downgrade()

    with engine.connect() as writer, ThreadPoolExecutor(1) as pool:
        tx = writer.begin()
        put(writer, "rate_snapshots", payload)
        writer_pid = writer.scalar(text("SELECT pg_backend_pid()"))
        job = pool.submit(downgrade)
        try:
            ddl_pid = pids.get(timeout=5)
            deadline = time.monotonic() + 4
            blocked = False
            blockers = []
            while time.monotonic() < deadline:
                blockers = observer_connection.scalar(
                    text("SELECT pg_blocking_pids(:pid)"),
                    {"pid": ddl_pid},
                )
                if writer_pid in blockers:
                    blocked = True
                    break
                time.sleep(0.01)
            assert blocked, (
                "downgrade must serialize with the actual writer; "
                f"worker={job.exception() if job.done() else 'running'}; "
                f"blockers={blockers}; writer={writer_pid}; ddl={ddl_pid}"
            )
            tx.commit()
            with pytest.raises(RuntimeError, match="history exists"):
                job.result(timeout=6)
            with engine.connect() as db:
                assert (
                    db.scalar(
                        text(
                            "SELECT count(*) FROM rate_snapshots WHERE id=:id"
                        ),
                        {"id": payload["id"]},
                    )
                    == 1
                )
        finally:
            if tx.is_active:
                tx.rollback()
