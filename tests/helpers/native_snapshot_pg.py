"""Prepared real-SQL snapshot observations; import/run needs a later PG grant.

PID comes from psycopg metadata. No preliminary reader SELECT is issued.
Settings are inspected only after the actual repository actor SELECT executes.
No query result or installed repository/transaction manager is replaced.
"""

import asyncio
import re
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.util.concurrency import await_only

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_paid_selection_interest import service
from tests.postgres_financial.test_work_entitlement_runtime import finish_work
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.miniapp.api import router


async def metadata_pid(session):
    """Checkout/BEGIN is allowed; no SQL query establishes a snapshot here."""
    connection = await session.connection()
    return (
        connection.sync_connection.connection.driver_connection.info.backend_pid
    )


async def finish_task(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class ActorGate:
    def __init__(self, phase):
        assert phase in ("before", "after")
        self.phase = phase
        self.reached = asyncio.Future()
        self.release = asyncio.Event()

    async def arrive(self, snapshot):
        if self.reached.done():
            return
        self.reached.set_result(snapshot)
        await asyncio.wait_for(self.release.wait(), 5)


class SnapshotTrace:
    """Observe the Container engine, including its gateway read."""

    def __init__(self, case, gate=None):
        self.engine = case.container.session_factory.kw["bind"].sync_engine
        self.gate = gate
        self.sql = []
        self.snapshots = []
        self.key = "native_snapshot_observation"

    def before(self, conn, cursor, statement, params, context, many):
        compact = " ".join(statement.upper().split())
        pid = conn.connection.driver_connection.info.backend_pid
        self.sql.append(dict(pid=pid, sql=compact))
        if compact.startswith("SET TRANSACTION"):
            assert "REPEATABLE READ" in compact and "READ ONLY" in compact
            snapshot = dict(
                pid=pid, statements=[], settings=None, actor_index=None
            )
            self.snapshots.append(snapshot)
            conn.info[self.key] = snapshot
        snapshot = conn.info.get(self.key)
        if snapshot is None:
            return
        snapshot["statements"].append(compact)
        if compact.startswith("SELECT") and snapshot["actor_index"] is None:
            assert "FROM USERS" in compact
            for field in ("USER_ID", "STATUS", "TELEGRAM_ID", "MAX_ID"):
                assert "USERS." + field in compact
            assert (
                context.compiled.statement.get_execution_options().get(
                    "autoflush"
                )
                is False
            )
            snapshot["actor_index"] = len(snapshot["statements"]) - 1
            snapshot["_actor_context"] = context
            if self.gate is not None and self.gate.phase == "before":
                await_only(self.gate.arrive(snapshot))

    def after(self, conn, cursor, statement, params, context, many):
        snapshot = conn.info.get(self.key)
        if snapshot is None or snapshot.get("_actor_context") is not context:
            return
        # These SHOWs follow the intended first SELECT; never move them earlier.
        snapshot.pop("_actor_context")
        snapshot["settings"] = {
            "isolation": conn.exec_driver_sql(
                "SHOW transaction_isolation"
            ).scalar_one(),
            "read_only": conn.exec_driver_sql(
                "SHOW transaction_read_only"
            ).scalar_one(),
        }
        if self.gate is not None and self.gate.phase == "after":
            await_only(self.gate.arrive(snapshot))

    def ended(self, conn):
        conn.info.pop(self.key, None)

    def __enter__(self):
        for name, listener in self.listeners():
            event.listen(self.engine, name, listener)
        return self

    def __exit__(self, *args):
        for name, listener in self.listeners():
            event.remove(self.engine, name, listener)
        for snapshot in self.snapshots:
            snapshot.pop("_actor_context", None)

    def listeners(self):
        return (
            ("before_cursor_execute", self.before),
            ("after_cursor_execute", self.after),
            ("commit", self.ended),
            ("rollback", self.ended),
        )

    def assert_read_only(self):
        forbidden = re.compile(
            r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP|LOCK)\b"
            r"|\bFOR\s+(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|SHARE)\b"
            r"|PG_(?:TRY_)?ADVISORY"
        )
        assert not [row for row in self.sql if forbidden.search(row["sql"])]
        for snapshot in self.snapshots:
            assert snapshot["actor_index"] == 1
            assert snapshot["statements"][0].startswith("SET TRANSACTION")
            assert snapshot["settings"] == {
                "isolation": "repeatable read",
                "read_only": "on",
            }

    def assert_native_denied_before_private(self):
        assert len(self.snapshots) == 1
        self.assert_read_only()
        statements = self.snapshots[0]["statements"]
        assert len([sql for sql in statements if sql.startswith("SELECT")]) == 1
        assert all(
            sql.startswith(("SET TRANSACTION", "SELECT USERS.", "SHOW "))
            for sql in statements
        )


class NativeSnapshotCase:
    def __init__(self, family, container, factory, ids, *, env=None, flow=None):
        self.family, self.container, self.factory = family, container, factory
        self.ids, self.env, self.flow = ids, env, flow
        self.actor_id = ids["client"]
        self.external = None
        self.extra_interest = None
        self.app = FastAPI()
        self.app.include_router(router, prefix="/miniapp")
        self.app.state.config = container._config
        self.app.state.dispatcher = container.build_bot_services()
        self.order_id = ids["order"]

    async def seed_actor(self, role="client"):
        self.actor_id = self.ids[role]
        self.external = str(uuid4().int % 10**14 + 1)
        async with self.factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == self.actor_id)
                .values(
                    telegram_id=self.external,
                    max_id=self.external,
                    country=None,
                )
            )
        return self.external

    def auth(self, platform, external=None):
        token = (
            self.container._config.bot.bot_token
            if platform == "telegram"
            else self.container._config.max_bot.token
        )
        return dict(
            platform=platform,
            init_data=generate_init_data(
                token,
                int(external or self.external),
                "Synthetic snapshot caller",
            ),
        )

    def path(self, order_id=None):
        order = order_id or self.order_id
        return {
            "partner": "/miniapp/api/partner/view",
            "selection": f"/miniapp/api/financial/orders/{order}/selection",
            "summary": f"/miniapp/api/orders/{order}/campaign-summary",
        }[self.family]

    async def post(self, platform, *, external=None, order_id=None, extra=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                self.path(order_id),
                json=self.auth(platform, external) | (extra or {}),
            )

    async def effects(self):
        """Verify effects through the fixture, outside the observed reader."""
        async with self.factory() as db:
            result = {}
            for name in (
                "users",
                "financial_wallets",
                "financial_obligations",
                "financial_movements",
                "outbox_events",
            ):
                result[name] = await db.scalar(
                    select(func.count()).select_from(Base.metadata.tables[name])
                )
            actor = (
                await db.execute(
                    select(
                        UserModel.telegram_id,
                        UserModel.max_id,
                        UserModel.country,
                        UserModel.status,
                    ).where(UserModel.user_id == self.actor_id)
                )
            ).one_or_none()
            result["actor"] = tuple(actor) if actor else None
            return result

    async def mutate_native(self, platform, change="remap", *, private=False):
        field = "telegram_id" if platform == "telegram" else "max_id"
        new_native = (
            str(uuid4().int % 10**14 + 1) if change == "remap" else None
        )
        async with self.factory.begin() as db:
            pid = await metadata_pid(db)
            await db.execute(text("SET LOCAL lock_timeout='2s'"))
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == self.actor_id)
                .values(**{field: new_native})
            )
            if change == "move":
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == self.ids["foreign"])
                    .values(**{field: self.external})
                )
            if private and self.family == "partner":
                await db.execute(
                    update(BloggerProfileModel)
                    .where(BloggerProfileModel.user_id == self.ids["creator"])
                    .values(confirmed=False)
                )
        if private and self.family == "selection":
            self.extra_interest = await service(self.env).respond(
                self.order_id, self.ids["second"]
            )
            assert self.extra_interest.accepted
        if private and self.family == "summary":
            await finish_work(self.env, self.flow)
        return dict(pid=pid, new_native=new_native)

    async def change_status(self, status):
        async with self.factory.begin() as db:
            pid = await metadata_pid(db)
            await db.execute(text("SET LOCAL lock_timeout='2s'"))
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == self.actor_id)
                .values(status=status)
            )
        return pid

    async def revoke_role(self, role):
        async with self.factory.begin() as db:
            pid = await metadata_pid(db)
            await db.execute(text("SET LOCAL lock_timeout='2s'"))
            if role == "manager":
                await db.execute(
                    delete(ManagerOrderModel).where(
                        ManagerOrderModel.order_id == self.order_id,
                        ManagerOrderModel.user_id == self.actor_id,
                    )
                )
            else:
                await db.execute(
                    delete(AdvertiserProfileModel).where(
                        AdvertiserProfileModel.user_id == self.actor_id
                    )
                )
        return pid

    def assert_old_private(self, data):
        if self.family == "partner":
            assert data["grade"]["verified_creators"] == 1
            assert data["network"]["total"] == 1
        elif self.family == "selection":
            assert data["positions"][0]["current"] is True
            assert data["positions"][1]["assignment_id"] is None
        else:
            assert data["source"] == "financial_positions"
            assert data["states"] == {"assigned": 1, "unassigned": 1}

    def assert_new_private(self, data):
        if self.family == "partner":
            assert data["grade"]["verified_creators"] == 0
            assert data["network"]["total"] == 1
        elif self.family == "selection":
            assert data["positions"][1]["creator_id"] == str(self.ids["second"])
            assert data["positions"][1]["assignment_id"] == str(
                self.extra_interest.assignment_id
            )
        else:
            assert data["states"] == {"success_final": 1, "unassigned": 1}

    async def seed_legacy_summary(self):
        """Existing legacy order shape plus the real interaction producer."""
        self.order_id = uuid4()
        interaction_service = self.app.state.dispatcher["interaction_service"]
        async with self.factory.begin() as db:
            db.add(
                OrderModel(
                    order_id=self.order_id,
                    advertiser_id=self.ids["client"],
                    product_link="synthetic legacy",
                    offer_text="legacy snapshot",
                    price=1,
                    bloggers_needed=1,
                    status="active",
                )
            )
            await db.flush()
            await interaction_service.get_or_create(
                self.order_id,
                self.ids["creator"],
                self.ids["client"],
                session=db,
            )

    async def dispose(self):
        await self.container.dispose()


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {"detail": code}
    assert response.headers["cache-control"] == "no-store"


def evidence(case, trace, writer, phase, platform):
    reader = trace.snapshots[0]
    assert reader["pid"] != writer
    return dict(
        family=case.family,
        platform=platform,
        phase=phase,
        reader_pid=reader["pid"],
        writer_pid=writer,
        settings=reader["settings"],
        completed=True,
        first_actor_index=reader["actor_index"],
        reader_statement_count=len(reader["statements"]),
        pid_source="psycopg_connection_info_backend_pid",
        settings_after_actual_actor_select=True,
    )
