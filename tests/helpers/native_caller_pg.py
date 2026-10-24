"""Real SQL/ASGI observations for native callers; no SQL-result substitutes."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import event, select, text, update

from tests.e2e.miniapp_helpers import generate_init_data
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.collaboration_api import create_collaboration_router
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.order_intake_api import create_order_intake_router


async def backend_pid(db):
    await db.execute(text("SET LOCAL statement_timeout='8s'"))
    await db.execute(text("SET LOCAL lock_timeout='6s'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def blocked_by(observer, waiting, blocker):
    for _ in range(250):
        pids = await observer.scalar(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting}
        )
        if blocker in pids:
            return tuple(pids)
        await asyncio.sleep(0.01)
    raise AssertionError("native_caller_expected_real_pid_wait_missing")


async def finish(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class ObservedTransactions:
    """Observe the installed TM's actual PID and commit boundary."""

    def __init__(self, original):
        self.original = original
        self.entered = None
        self.before_commit = None
        self.release_commit = None

    @asynccontextmanager
    async def transaction(self):
        async with self.original.transaction() as db:
            pid = await backend_pid(db)
            connection = await db.connection()
            connection.info["native_caller_reader"] = pid
            if self.entered is not None and not self.entered.done():
                self.entered.set_result(pid)
            try:
                yield db
                if self.before_commit is not None:
                    if not self.before_commit.done():
                        self.before_commit.set_result(pid)
                    await asyncio.wait_for(self.release_commit.wait(), 5)
            finally:
                connection.info.pop("native_caller_reader", None)


@asynccontextmanager
async def observe_sql(factory):
    """Observe tagged service connections; retain IDs and lock strength."""
    engine = factory.kw["bind"].sync_engine
    rows = []

    def before(conn, cursor, statement, parameters, context, many):
        pid = conn.info.get("native_caller_reader")
        if pid is None:
            return
        compact = " ".join(statement.upper().split())
        values = context.compiled_parameters[0] if context.compiled else {}
        kind, identity, strength = "other", None, None
        if "FROM USERS" in compact and "FOR " in compact:
            kind = "user"
            identity = values.get("user_id_1")
            strength = compact.split("FOR ", 1)[1]
        elif "FROM ORDER_ITEMS" in compact and "FOR UPDATE" in compact:
            kind = "item"
            identity = values.get("paid_item_id_1")
            strength = "UPDATE"
        rows.append(
            dict(kind=kind, identity=identity, strength=strength, pid=pid)
        )

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield rows
    finally:
        event.remove(engine, "before_cursor_execute", before)


def assert_user_item_order(rows, expected_users, item=None):
    locks = [row for row in rows if row["kind"] in ("user", "item")]
    users = [row for row in locks if row["kind"] == "user"]
    assert [row["identity"] for row in users] == sorted(set(expected_users))
    assert all(row["strength"] == "NO KEY UPDATE" for row in users)
    if item is not None:
        item_positions = [
            i for i, row in enumerate(locks) if row["kind"] == "item"
        ]
        assert item_positions, "native_caller_item_lock_not_observed"
        assert item_positions[0] == len(users)
        assert all(row["kind"] == "item" for row in locks[item_positions[0] :])
        assert all(
            row["identity"] == item for row in locks if row["kind"] == "item"
        )


class NativeCallerCase:
    """Existing fixture facts plus installed SQL repositories/TM/resolver."""

    def __init__(self, kind, pg, clock, ids, command):
        self.kind, self.pg, self.clock, self.ids = kind, pg, clock, ids
        self.command = command
        config = AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "MAX_BOT_TOKEN": "max-test-token",
                "DATABASE_URL": pg.url.render_as_string(hide_password=False),
                "DB_POOL_SIZE": 6,
                "DB_MAX_OVERFLOW": 0,
                "FINANCIAL_CORE_ENABLED": True,
                "FINANCIAL_NEW_ORDERS_ENABLED": True,
                "KAFKA_ENABLED": False,
                "USE_REDIS_STORAGE": False,
                "REDIS_URL": "",
            }
        )
        self.container = Container(config)
        self.factory = self.container.session_factory
        self.services = self.container.build_bot_services()
        self.service = self.services[
            "order_intake_service"
            if kind == "intake"
            else "collaboration_service"
        ]
        self.service.clock = clock
        self.transactions = ObservedTransactions(
            self.container.transaction_manager
        )
        if kind == "intake":
            self.service.transactions = self.transactions
        self.services["transaction_manager"] = self.transactions
        self.native = {}
        self.resolved = self.release_resolver = None
        self.actor_role = "client"

    async def seed_native(self):
        async with self.factory.begin() as db:
            for role in ("client", "creator", "manager"):
                if self.ids.get(role) is None:
                    continue
                native = tuple(str(uuid4().int % 10**14 + 1) for _ in range(2))
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == self.ids[role])
                    .values(telegram_id=native[0], max_id=native[1])
                )
                self.native[role] = native

    async def resolver(self, request, init_data, *, platform):
        proof = await resolve_financial_principal(
            request, init_data, platform=platform
        )
        if self.resolved is not None:
            if not self.resolved.done():
                self.resolved.set_result(proof)
            await asyncio.wait_for(self.release_resolver.wait(), 5)
        return proof

    def app(self):
        app = FastAPI()
        create = (
            create_order_intake_router
            if self.kind == "intake"
            else create_collaboration_router
        )
        app.include_router(create(self.resolver))
        app.state.config = self.container._config
        app.state.dispatcher = self.services
        return app

    def auth(self, platform, role=None, native=None):
        role = role or self.actor_role
        external = native or self.native[role][platform == "max"]
        return dict(
            platform=platform,
            init_data=generate_init_data(
                "test-token" if platform == "telegram" else "max-test-token",
                int(external),
                "Synthetic native caller",
            ),
        )

    def request(self, operation, platform):
        auth = self.auth(platform)
        if self.kind == "intake":
            path = "/financial/orders"
            if operation == "policies":
                return path + "/policies", auth
            values = asdict(self.command)
            values.pop("client_id")
            values.update(
                honorarium=str(self.command.honorarium),
                selection_due_at=self.command.selection_due_at.isoformat(),
                accompaniment_ordinals=sorted(
                    self.command.accompaniment_ordinals
                ),
                order_type=self.command.order_type.value,
            )
            return path, auth | values
        path = f"/collaborations/{self.ids['assignment']}"
        if operation == "status":
            return path + "/status", auth
        return path + "/command", auth | dict(
            action="assign",
            operation_key="native-assign",
            expected_version=0,
            due_at=(self.clock.now() + timedelta(days=2)).isoformat(),
            terms_reference="native caller approved brief",
        )

    async def post(self, operation, platform, *, payload=None):
        path, body = self.request(operation, platform)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app()),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                path, json=payload if payload is not None else body
            )

    async def seed_operation(self, operation, platform):
        if operation in ("replay", "status"):
            response = await self.post(
                "create" if self.kind == "intake" else "command", platform
            )
            assert response.status_code == 200, response.text
            return response.json()
        return None

    async def snapshot(self):
        names = (
            (
                "orders",
                "order_items",
                "order_intake_receipts",
                "accompaniment_leads",
                "accompaniment_lead_outbox",
            )
            if self.kind == "intake"
            else (
                "financial_collaborations",
                "financial_collaboration_events",
                "financial_collaboration_notices",
                "financial_collaboration_schedules",
            )
        )
        result = {}
        async with self.factory.begin() as db:
            for name in (*names, "outbox_events"):
                table = Base.metadata.tables[name]
                if name == "outbox_events":
                    statement = select(table).where(
                        table.c.aggregate_id.in_(
                            [
                                str(value)
                                for key, value in self.ids.items()
                                if key in ("order", "assignment")
                            ]
                        )
                    )
                elif "order_id" in table.c:
                    statement = select(table).where(
                        table.c.order_id == self.ids["order"]
                    )
                else:
                    statement = select(table).where(
                        table.c.assignment_id == self.ids["assignment"]
                    )
                result[name] = sorted(
                    json.dumps(dict(row), sort_keys=True, default=str)
                    for row in (await db.execute(statement)).mappings()
                )
        return result

    async def dispose(self):
        await self.container.dispose()
