"""Real manager-set expansion after accepted delivery, before final User locks.

The provider boundary uses the existing synthetic Bot and actual receipt
adapter. SQL source facts/results and the expected refresh error are genuine;
the only service hook observes and pauses before existing User locks.
"""

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_paid_selection_delivery import (
    capture_env,
    delivery_env,
    rows,
    state,
)
from ugc_bot.domain.entities import ManagerOrder
from ugc_bot.infrastructure.db.models import OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
)
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
)
from ugc_bot.infrastructure.db.repositories.support import (
    SqlAlchemyManagerOrderRepository,
)

__all__ = ["capture_env", "delivery_env"]

SCOPE_CHANGED = "selection_scope_changed_retry_required"


async def driver_pid(session):
    connection = await session.connection()
    return (
        connection.sync_connection.connection.driver_connection.info.backend_pid
    )


class SqlTrace:
    """Observe actual SQL/driver IDs without consuming or replacing results."""

    def __init__(self, engine):
        self.engine = engine.sync_engine
        self.statements: list[dict] = []
        self.ends: list[dict] = []

    def before(self, connection, cursor, statement, params, context, many):
        sql = " ".join(statement.upper().split())
        user_ids = ()
        if "FROM USERS" in sql and "FOR NO KEY UPDATE" in sql:
            user_ids = tuple(
                str(value)
                for bound in context.compiled_parameters
                for value in bound.values()
                if isinstance(value, UUID)
            )
        self.statements.append(
            dict(
                pid=connection.connection.driver_connection.info.backend_pid,
                sql=sql,
                user_ids=user_ids,
            )
        )

    def committed(self, connection):
        self.ended(connection, "commit")

    def rolled_back(self, connection):
        self.ended(connection, "rollback")

    def ended(self, connection, outcome):
        self.ends.append(
            dict(
                pid=connection.connection.driver_connection.info.backend_pid,
                outcome=outcome,
                statement_count=len(self.statements),
            )
        )

    def listeners(self):
        return (
            ("before_cursor_execute", self.before),
            ("commit", self.committed),
            ("rollback", self.rolled_back),
        )

    def __enter__(self):
        for name, listener in self.listeners():
            event.listen(self.engine, name, listener)
        return self

    def __exit__(self, *args):
        for name, listener in self.listeners():
            event.remove(self.engine, name, listener)


@pytest.fixture(scope="session")
def selection_finish_pg_evidence():
    evidence = []
    yield evidence
    destination = os.environ.get("SELECTION_FINISH_PG_EVIDENCE_PATH")
    if destination:
        Path(destination).write_text(json.dumps(evidence, indent=2) + "\n")


async def add_manager_user_first(env, factory, manager):
    """Declared fixture writer using genuine User/order locks and repository.

    This adds a real current manager routing row, without inventing a new
    production assignment flow or changing the immutable accepted interest.
    """
    users = tuple(sorted({env["client"], env["creator"], manager}, key=str))
    async with factory.begin() as session:
        pid = await driver_pid(session)
        await SqlAlchemyPaidSelectionRepository().lock_users(
            users, session=session
        )
        await SqlAlchemyFinancialItemRepository().lock_order(
            env["order"], session=session
        )
        assert (
            await session.scalar(
                select(OrderModel.order_id)
                .where(OrderModel.order_id == env["order"])
                .with_for_update()
            )
            == env["order"]
        )
        await SqlAlchemyManagerOrderRepository(factory).save(
            ManagerOrder(manager, env["order"], env["worker"].clock.now()),
            session=session,
        )
    return pid


def assert_user_locks_before_order(statements, expected_users):
    locked = [row for row in statements if row["user_ids"]]
    assert [user for row in locked for user in row["user_ids"]] == [
        str(user) for user in sorted(expected_users, key=str)
    ]
    order_barrier = next(
        i
        for i, row in enumerate(statements)
        if "PG_ADVISORY_XACT_LOCK(HASHTEXTEXTENDED" in row["sql"]
    )
    assert all(not row["user_ids"] for row in statements[order_barrier:]), (
        "User locks must not be acquired after order coordination"
    )
    return order_barrier


@pytest.mark.asyncio
async def test_real_manager_added_after_finish_discovery_retains_receipt(
    delivery_env, monkeypatch, selection_finish_pg_evidence
):
    env = delivery_env
    worker, bot = env["worker"], env["bot"]
    actor_engine = env["container"].session_factory.kw["bind"]
    assert env["interest"].manager_id is None
    assert rows(env, "manager_orders") == []
    manager = env["other_creator"]
    initial_users = {env["client"], env["creator"]}
    assert manager not in initial_users
    attempt = await worker.prepare(env["interest"].job_id)
    assert attempt is not None and attempt.channel == "telegram"
    original_attempts = rows(env, "paid_selection_delivery_attempts")
    original_interests = rows(env, "paid_selection_interests")
    original_items = rows(env, "order_items")
    original_obligations = rows(env, "financial_obligations")
    (original_job,) = rows(env, "paid_selection_delivery_jobs")
    assert state(env) == "paid"

    writer_engine = create_async_engine(
        env["pg"].url, pool_size=1, max_overflow=0, pool_timeout=5
    )
    writer_factory = async_sessionmaker(writer_engine, expire_on_commit=False)
    discovered = asyncio.get_running_loop().create_future()
    release = asyncio.Event()
    armed, finish_start, sender_checked_out = False, None, None
    delivery = None
    original_lock_users = SqlAlchemyPaidSelectionRepository.lock_users

    async def observe_discovery(repository, users, *, session):
        if armed and session.bind is actor_engine:
            assert not discovered.done(), "finish must not retry source locks"
            assert set(users) == initial_users
            discovered.set_result(
                dict(
                    pid=await driver_pid(session),
                    user_ids=tuple(str(user) for user in users),
                    sql_count=len(actor_trace.statements),
                )
            )
            await asyncio.wait_for(release.wait(), 8)
        return await original_lock_users(repository, users, session=session)

    async def accepted_in_flight():
        nonlocal armed, finish_start, sender_checked_out
        sender_checked_out = actor_engine.pool.checkedout()
        assert sender_checked_out == 0
        assert actor_trace.ends[-1]["outcome"] == "commit"
        # Existing Bot has separately read the committed started row, and its
        # real receipt adapter returns the accepted reference after this hook.
        finish_start = len(actor_trace.statements)
        armed = True

    monkeypatch.setattr(
        SqlAlchemyPaidSelectionRepository, "lock_users", observe_discovery
    )
    bot.hook = accepted_in_flight
    try:
        with (
            SqlTrace(actor_engine) as actor_trace,
            SqlTrace(writer_engine) as writer_trace,
        ):
            delivery = asyncio.create_task(worker.deliver(attempt))
            actor = await asyncio.wait_for(discovered, 4)
            assert finish_start is not None
            prospective = actor_trace.statements[
                finish_start : actor["sql_count"]
            ]
            assert any(
                "FROM MANAGER_ORDERS" in row["sql"] for row in prospective
            )
            assert not any(
                "FOR " in row["sql"] or "PG_ADVISORY" in row["sql"]
                for row in prospective
            ), "pause must precede the actual first User lock"
            writer_pid = await asyncio.wait_for(
                add_manager_user_first(env, writer_factory, manager), 5
            )
            assert actor["pid"] != writer_pid
            assert len({actor["pid"], writer_pid}) == 2
            assert not delivery.done()
            assert [row["user_id"] for row in rows(env, "manager_orders")] == [
                manager
            ]
            release.set()
            # With the old _finish this raises the genuine scope refresh
            # ValueError after provider acceptance and before retention.
            await asyncio.wait_for(delivery, 5)

        finish_sql = actor_trace.statements[finish_start:]
        assert {row["pid"] for row in finish_sql} == {actor["pid"]}
        assert {row["pid"] for row in writer_trace.statements} == {writer_pid}
        actor_order = assert_user_locks_before_order(finish_sql, initial_users)
        writer_order = assert_user_locks_before_order(
            writer_trace.statements, initial_users | {manager}
        )
        assert any(
            "FROM MANAGER_ORDERS" in row["sql"] and "FOR UPDATE" in row["sql"]
            for row in finish_sql[actor_order:]
        )
        assert any(
            row["sql"].startswith("INSERT INTO MANAGER_ORDERS")
            for row in writer_trace.statements[writer_order:]
        )
        assert not any(
            row["sql"].startswith("INSERT INTO PAID_SELECTION_ACCEPTED")
            or row["sql"].startswith("UPDATE ORDER_ITEMS")
            for row in finish_sql
        )
        assert [row["outcome"] for row in actor_trace.ends] == [
            "commit",
            "commit",
        ]
        assert [row["outcome"] for row in writer_trace.ends] == ["commit"]
        (outcome,) = [
            row
            for row in rows(env, "paid_selection_delivery_outcomes")
            if row["kind"] == "transport"
        ]
        assert outcome["outcome_id"] == uuid5(attempt.attempt_id, "transport")
        assert outcome["job_id"] == attempt.job_id
        assert outcome["order_id"] == attempt.order_id
        assert outcome["attempt_id"] == attempt.attempt_id
        assert outcome["status"] == "accepted"
        assert outcome["provider_reference"] == f"{int(attempt.address)}:7"
        assert outcome["reason"] == SCOPE_CHANGED
        assert outcome["applied"] is False
        assert rows(env, "paid_selection_accepted_deliveries") == []
        assert (
            rows(env, "paid_selection_delivery_attempts") == original_attempts
        )
        assert rows(env, "paid_selection_interests") == original_interests
        assert rows(env, "order_items") == original_items
        assert rows(env, "financial_obligations") == original_obligations
        assert rows(env, "paid_selection_delivery_jobs") == [
            dict(original_job) | {"state": "obsolete"}
        ]
        assert len(bot.calls) == 1 and state(env) == "paid"
        selection_finish_pg_evidence.append(
            dict(
                case="manager_added_after_finish_discovery",
                actor_pid=actor["pid"],
                writer_pid=writer_pid,
                initial_user_ids=sorted(str(user) for user in initial_users),
                discovered_user_ids=actor["user_ids"],
                new_manager_id=str(manager),
                sender_checked_out=sender_checked_out,
                provider_reference=outcome["provider_reference"],
                retained_attempt_id=str(outcome["attempt_id"]),
                retained_outcome_id=str(outcome["outcome_id"]),
                applied=False,
                actor_pre_send_sql=actor_trace.statements[:finish_start],
                actor_sql=finish_sql,
                writer_sql=writer_trace.statements,
                actor_transactions=actor_trace.ends,
                writer_transactions=writer_trace.ends,
            )
        )
    finally:
        release.set()
        if delivery is not None:
            if not delivery.done():
                delivery.cancel()
            await asyncio.wait_for(
                asyncio.gather(delivery, return_exceptions=True), 5
            )
        await asyncio.wait_for(writer_engine.dispose(), 5)
