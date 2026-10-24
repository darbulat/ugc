"""Real admin manager replacement serializes with lifecycle authorization."""

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from tests.helpers.native_caller_pg import (
    ObservedTransactions,
    backend_pid,
    blocked_by,
    finish,
)
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_pg,
)
from tests.postgres_financial.test_collaboration_persistence import (
    command,
    execute,
    start,
)
from ugc_bot.admin import app as admin_app
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyManagerOrderRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

__all__ = ["collaboration_pg"]


@pytest.fixture(scope="session")
def manager_membership_evidence():
    records = []
    yield records
    if path := os.environ.get("MANAGER_MEMBERSHIP_EVIDENCE_PATH"):
        Path(path).write_text(json.dumps(records, indent=2) + "\n")


@pytest_asyncio.fixture
async def manager_race(collaboration_pg, monkeypatch, action):
    factory, service, repo, clock, data = collaboration_pg
    if action == "start":
        await execute(
            factory,
            service,
            command(
                data,
                "assign",
                "client",
                0,
                due_at=clock.at + timedelta(days=2),
                terms_reference="client-consented:membership-race",
            ),
        )
    else:
        await start(collaboration_pg)
    external = str(uuid4().int % 10**14 + 1)
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["manager"])
            .values(telegram_id=external)
        )
    transactions = ObservedTransactions(SessionTransactionManager(factory))
    writer = ManagerService(
        SqlAlchemyManagerOrderRepository(factory),
        SqlAlchemyUserRepository(factory),
        SqlAlchemyOrderRepository(factory),
        transaction_manager=transactions,
    )
    # Keep the admin parser and its actual service/repos/transaction writer.
    monkeypatch.setattr(
        admin_app,
        "_get_admin_container",
        lambda: SimpleNamespace(build_manager_service=lambda: writer),
    )
    return SimpleNamespace(
        factory=factory,
        service=service,
        repo=repo,
        data=data,
        transactions=transactions,
        principal=AuthenticatedMessengerPrincipal(
            data["manager"], "telegram", external
        ),
        command=command(data, action, "manager", 1 if action == "start" else 2),
    )


async def call(race, operation, db):
    if operation == "status":
        return await race.service.get_authenticated(
            race.data["assignment"], race.principal, session=db
        )
    return await race.service.execute_authenticated(
        race.command, race.principal, session=db
    )


async def seed_replay(race, operation):
    if operation == "replay":
        async with race.factory.begin() as db:
            await call(race, operation, db)


async def facts(race):
    result = {}
    async with race.factory() as db:
        for name in (
            "financial_collaborations",
            "financial_collaboration_events",
            "financial_collaboration_notices",
            "financial_collaboration_schedules",
            "outbox_events",
        ):
            table = Base.metadata.tables[name]
            predicate = (
                table.c.aggregate_id == str(race.data["assignment"])
                if name == "outbox_events"
                else table.c.assignment_id == race.data["assignment"]
            )
            rows = await db.execute(
                select(table)
                .where(predicate)
                .order_by(*table.primary_key.columns)
            )
            result[name] = tuple(dict(row) for row in rows.mappings())
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "request_confirmation"])
@pytest.mark.parametrize("operation", ["command", "status", "replay"])
async def test_admin_revoke_waits_until_authorized_manager_transaction_ends(
    manager_race, manager_membership_evidence, operation, action
):
    race = manager_race
    await seed_replay(race, operation)
    race.transactions.entered = asyncio.Future()
    task = None
    try:
        async with race.factory.begin() as reader:
            reader_pid = await backend_pid(reader)
            assert await call(race, operation, reader) is not None
            task = asyncio.create_task(
                admin_app._update_order_managers(race.data["order"], "")
            )
            writer_pid = await asyncio.wait_for(race.transactions.entered, 3)
            async with race.factory() as observer:
                blockers = await blocked_by(observer, writer_pid, reader_pid)
            assert not task.done()
        await asyncio.wait_for(task, 4)
        async with race.factory() as db:
            assert (
                await db.scalar(
                    select(ManagerOrderModel.user_id).where(
                        ManagerOrderModel.order_id == race.data["order"]
                    )
                )
                is None
            )
        manager_membership_evidence.append(
            dict(
                direction="manager_first",
                action=action,
                operation=operation,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                completed=True,
            )
        )
    finally:
        await finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "request_confirmation"])
@pytest.mark.parametrize("operation", ["command", "status", "replay"])
async def test_committing_admin_revoke_prevents_stale_manager_authorization(
    manager_race, manager_membership_evidence, operation, action
):
    race = manager_race
    await seed_replay(race, operation)
    before = await facts(race)
    race.transactions.before_commit = asyncio.Future()
    race.transactions.release_commit = asyncio.Event()
    entered = asyncio.Future()

    async def read():
        async with race.factory.begin() as db:
            entered.set_result(await backend_pid(db))
            return await call(race, operation, db)

    writer = asyncio.create_task(
        admin_app._update_order_managers(race.data["order"], "")
    )
    reader = None
    try:
        writer_pid = await asyncio.wait_for(race.transactions.before_commit, 3)
        reader = asyncio.create_task(read())
        reader_pid = await asyncio.wait_for(entered, 3)
        async with race.factory() as observer:
            blockers = await blocked_by(observer, reader_pid, writer_pid)
        assert not reader.done()
        race.transactions.release_commit.set()
        await asyncio.wait_for(writer, 4)
        code = (
            "collaboration_view_forbidden"
            if operation == "status"
            else "assignment_actor_required"
        )
        with pytest.raises(PermissionError, match=code):
            await asyncio.wait_for(reader, 4)
        assert await facts(race) == before
        manager_membership_evidence.append(
            dict(
                direction="admin_first",
                action=action,
                operation=operation,
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                unchanged_facts=True,
                completed=True,
            )
        )
    finally:
        race.transactions.release_commit.set()
        await finish(reader)
        await finish(writer)


@pytest.mark.asyncio
async def test_direct_scope_rejects_order_changed_while_waiting_for_item(
    collaboration_pg, manager_membership_evidence
):
    factory, _, repo, _, data = collaboration_pg
    other_order, item, assignment = (uuid4() for _ in range(3))
    async with factory.begin() as db:
        # Uncaptured items can still move; captured fixtures are immutable.
        for model, identity, changes in (
            (OrderModel, data["order"], dict(order_id=other_order)),
            (
                OrderItemModel,
                data["item"],
                dict(paid_item_id=item, ordinal=2, captured_at=None),
            ),
            (
                ItemAssignmentModel,
                data["assignment"],
                dict(assignment_id=assignment, paid_item_id=item),
            ),
        ):
            original = await db.get(model, identity)
            values = {
                column.key: getattr(original, column.key)
                for column in model.__table__.columns
            }
            db.add(model(**(values | changes)))
            await db.flush()
    entered = asyncio.Future()

    async def read():
        async with factory.begin() as db:
            entered.set_result(await backend_pid(db))
            return await repo.lock_scope(assignment, session=db)

    reader = None
    try:
        async with factory.begin() as writer:
            writer_pid = await backend_pid(writer)
            await writer.execute(
                update(OrderItemModel)
                .where(OrderItemModel.paid_item_id == item)
                .values(order_id=other_order)
            )
            reader = asyncio.create_task(read())
            reader_pid = await asyncio.wait_for(entered, 3)
            blockers = await blocked_by(writer, reader_pid, writer_pid)
            await writer.commit()
            with pytest.raises(ValueError, match="collaboration_scope_changed"):
                await asyncio.wait_for(reader, 4)
        manager_membership_evidence.append(
            dict(
                direction="direct_item_move",
                reader_pid=reader_pid,
                writer_pid=writer_pid,
                blockers=blockers,
                completed=True,
            )
        )
    finally:
        await finish(reader)
