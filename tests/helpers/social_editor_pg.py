"""Real social editor SQL observations, without replacing query results.

Only private synthetic fixture rows are changed. PID comes from psycopg driver
metadata; transaction settings are inspected after the actual first actor read.
"""

import asyncio
import re
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.util.concurrency import await_only

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.config import AppConfig, MaxBotConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import UserStatus, WorkFormat
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.social_models import SocialAccountModel
from ugc_bot.miniapp.api import router

ACTOR = "SELECT USERS.USER_ID, USERS.STATUS, USERS.TELEGRAM_ID, USERS.MAX_ID"


async def driver_pid(session):
    connection = await session.connection()
    return (
        connection.sync_connection.connection.driver_connection.info.backend_pid
    )


async def finish(task):
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

    async def arrive(self, transaction):
        if self.reached.done():
            return
        self.reached.set_result(transaction)
        await asyncio.wait_for(self.release.wait(), 8)


class EditorTrace:
    """Observe all Container SQL, separating gateway and facade transactions."""

    key = "social_editor_observation"

    def __init__(self, case, gate=None):
        self.engine = case.container.session_factory.kw["bind"].sync_engine
        self.gate, self.sql, self.transactions = gate, [], []

    def before(self, conn, cursor, statement, params, context, many):
        sql = " ".join(statement.upper().split())
        pid = conn.connection.driver_connection.info.backend_pid
        self.sql.append(dict(pid=pid, sql=sql))
        transaction = conn.info.get(self.key)
        if sql.startswith("SET TRANSACTION") or (
            sql.startswith(ACTOR) and transaction is None
        ):
            transaction = dict(pid=pid, sql=[], settings=None, ended=None)
            self.transactions.append(transaction)
            conn.info[self.key] = transaction
        if transaction is None:
            return
        transaction["sql"].append(sql)
        if sql.startswith(ACTOR):
            assert (
                context.compiled.statement.get_execution_options().get(
                    "autoflush"
                )
                is False
            )
            transaction["actor_index"] = len(transaction["sql"]) - 1
            transaction["actor_context"] = context
            if self.gate is not None and self.gate.phase == "before":
                await_only(self.gate.arrive(transaction))

    def after(self, conn, cursor, statement, params, context, many):
        transaction = conn.info.get(self.key)
        if (
            transaction is None
            or transaction.get("actor_context") is not context
        ):
            return
        transaction.pop("actor_context")
        if (
            "FOR NO KEY UPDATE"
            not in transaction["sql"][transaction["actor_index"]]
        ):
            # Never inspect settings before the actual actor SELECT.
            transaction["settings"] = dict(
                isolation=conn.exec_driver_sql(
                    "SHOW transaction_isolation"
                ).scalar_one(),
                read_only=conn.exec_driver_sql(
                    "SHOW transaction_read_only"
                ).scalar_one(),
            )
        if self.gate is not None and self.gate.phase == "after":
            await_only(self.gate.arrive(transaction))

    def committed(self, conn):
        self.ended(conn, "commit")

    def rolled_back(self, conn):
        self.ended(conn, "rollback")

    def ended(self, conn, outcome):
        transaction = conn.info.pop(self.key, None)
        if transaction is not None:
            transaction.pop("actor_context", None)
            transaction["ended"] = outcome

    def listeners(self):
        return (
            ("before_cursor_execute", self.before),
            ("after_cursor_execute", self.after),
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

    def only(self):
        assert len(self.transactions) == 1
        return self.transactions[0]

    def assert_read_only(self):
        transaction = self.only()
        sql = transaction["sql"]
        assert transaction["actor_index"] == 1
        assert sql[0] == (
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        assert transaction["settings"] == dict(
            isolation="repeatable read", read_only="on"
        )
        forbidden = re.compile(
            r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|ALTER|DROP|LOCK)\b"
            r"|\bFOR\s+(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|SHARE)\b"
            r"|PG_(?:TRY_)?ADVISORY"
        )
        assert not [row for row in self.sql if forbidden.search(row["sql"])]

    def assert_actor_only(self):
        sql = self.only()["sql"]
        assert len([row for row in sql if row.startswith("SELECT")]) == 1
        assert all(
            row.startswith(("SET TRANSACTION", ACTOR, "SHOW ")) for row in sql
        )

    def assert_user_first_write(self):
        transaction = self.only()
        sql = transaction["sql"]
        assert transaction["actor_index"] == 0
        assert "FOR NO KEY UPDATE" in sql[0]
        profile = next(
            i for i, row in enumerate(sql) if "FROM BLOGGER_PROFILES" in row
        )
        social = next(
            i
            for i, row in enumerate(sql)
            if "FROM CREATOR_SOCIAL_ACCOUNTS" in row
        )
        assert 0 < profile < social
        assert "FOR SHARE" in sql[profile]
        assert "FOR UPDATE" in sql[social]
        assert len([row for row in sql if "FROM USERS" in row]) == 1
        assert not any(
            word in row
            for row in sql
            for word in (
                "PG_ADVISORY",
                "WALLET",
                "ORDER_ITEMS",
                "HISTORY",
                "CAMPAIGN",
            )
        )


class SocialEditorCase:
    def __init__(self, pg):
        config = AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "DATABASE_URL": pg.url.render_as_string(hide_password=False),
                "KAFKA_ENABLED": False,
                "USE_REDIS_STORAGE": False,
                "REDIS_URL": "",
            }
        )
        config.max_bot = MaxBotConfig(MAX_BOT_TOKEN="max-test-token")
        self.container = Container(config)
        self.repos = self.container.build_repos()
        self.services = self.container.build_bot_services()
        self.service = self.services["social_account_service"]
        assert self.service.editor_repository is self.service.account_repo
        self.engine = create_async_engine(pg.url, pool_size=3, max_overflow=0)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/miniapp")
        self.app.state.config = config
        self.app.state.dispatcher = self.services
        self.external = str(uuid4().int % 10**13 + 1)
        self.user = self.profile = None
        self.account_id = uuid4()

    async def seed(self, *, profile=True, confirmed=True):
        self.user = await create_test_user(
            self.repos["user_repo"],
            telegram_id=self.external,
            max_id=self.external,
            country=None,
        )
        if profile:
            # Current production profile writer, including its User-first lock.
            self.profile = await create_test_blogger_profile(
                self.repos["blogger_repo"],
                self.user.user_id,
                instagram_url=f"https://instagram.com/synthetic_{self.external}_old",
                confirmed=confirmed,
            )

    def principal(self, platform):
        return AuthenticatedMessengerPrincipal(
            self.user.user_id, platform, self.external
        )

    def body(self, action, platform, *, external=None, extra=None):
        result = dict(
            platform=platform,
            init_data=generate_init_data(
                "test-token" if platform == "telegram" else "max-test-token",
                int(external or self.external),
                "Synthetic social editor",
            ),
        )
        if action == "save":
            result.update(
                network="youtube", url="https://youtube.com/@synthetic"
            )
        if action == "remove":
            result.update(account_id=str(self.account_id))
        return result | (extra or {})

    async def post(self, action, platform, *, external=None, extra=None):
        suffix = "" if action == "list" else "/" + action
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/miniapp/api/social/accounts" + suffix,
                json=self.body(
                    action, platform, external=external, extra=extra
                ),
            )

    async def seed_account(self, platform="youtube"):
        response = await self.post(
            "save",
            "telegram",
            extra=dict(
                network=platform,
                url={
                    "youtube": "https://youtube.com/@synthetic_old",
                    "tiktok": "https://tiktok.com/@synthetic_old",
                    "telegram": "https://t.me/synthetic_old",
                }[platform],
            ),
        )
        assert response.status_code == 200, response.text
        self.account_id = UUID(response.json()["account"]["account_id"])
        return response.json()["account"]

    async def effects(self):
        async with self.factory() as db:
            user = (
                await db.execute(
                    select(
                        UserModel.telegram_id,
                        UserModel.max_id,
                        UserModel.country,
                        UserModel.status,
                    ).where(UserModel.user_id == self.user.user_id)
                )
            ).one()
            accounts = (
                await db.execute(
                    select(SocialAccountModel.__table__)
                    .where(SocialAccountModel.user_id == self.user.user_id)
                    .order_by(SocialAccountModel.account_id)
                )
            ).all()
            return dict(
                user=tuple(user),
                accounts=accounts,
                users=await db.scalar(
                    select(func.count()).select_from(UserModel)
                ),
            )

    async def mutate(self, change, platform, *, ready=None):
        """Committed raw private SQL fixture changes target DB boundaries.

        Profile changes use the admitted production repository writer, which
        itself takes the actor User first. Native/status changes are raw SQL
        fixtures (the UPDATE still acquires its actual conflicting row lock).
        """
        async with self.factory.begin() as db:
            pid = await driver_pid(db)
            if ready is not None:
                ready.set_result(pid)
            await db.execute(text("SET LOCAL lock_timeout='6s'"))
            if change == "profile":
                await self.repos["blogger_repo"].save(
                    replace(self.profile, confirmed=False), session=db
                )
            else:
                values = (
                    {
                        platform + "_id": None
                        if change == "clear"
                        else str(uuid4().int % 10**13 + 1)
                    }
                    if change in ("clear", "remap")
                    else {"status": change}
                )
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == self.user.user_id)
                    .values(**values)
                )
        return pid

    async def coherent_change(self, change, platform):
        """User-fenced, explicitly raw private fixture account replacement."""
        async with self.factory.begin() as db:
            pid = await driver_pid(db)
            await db.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == self.user.user_id)
                .with_for_update(key_share=True)
            )
            if change == "native":
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == self.user.user_id)
                    .values(**{platform + "_id": str(uuid4().int % 10**13 + 1)})
                )
            elif change == "status":
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == self.user.user_id)
                    .values(status=UserStatus.BLOCKED.value)
                )
            await self.repos["blogger_repo"].save(
                replace(
                    self.profile,
                    confirmed=False,
                    instagram_url=f"https://instagram.com/synthetic_{self.external}_new",
                    work_format=WorkFormat.ADS_IN_ACCOUNT,
                ),
                session=db,
            )
            await db.execute(
                delete(SocialAccountModel).where(
                    SocialAccountModel.user_id == self.user.user_id
                )
            )
            at = datetime.now(timezone.utc)
            await db.execute(
                SocialAccountModel.__table__.insert().values(
                    account_id=uuid4(),
                    user_id=self.user.user_id,
                    platform="youtube",
                    url="https://youtube.com/@synthetic_new",
                    handle="synthetic_new",
                    verified=False,
                    work_format="ads_in_account",
                    created_at=at,
                    updated_at=at,
                )
            )
        return pid

    async def dispose(self):
        await self.container.dispose()
        await self.engine.dispose()


async def observe_wait(case, waiter, blocker):
    """Observer must see an actual non-granted lock and its real blocker."""
    async with case.factory() as db:
        observer = await driver_pid(db)
        assert len({observer, waiter, blocker}) == 3
        for _ in range(200):
            row = (
                await db.execute(
                    text(
                        "SELECT wait_event_type, "
                        "pg_blocking_pids(pid) AS blockers, "
                        "EXISTS(SELECT 1 FROM pg_locks l WHERE l.pid=a.pid "
                        "AND NOT l.granted) AS ungranted "
                        "FROM pg_stat_activity a WHERE pid=:pid"
                    ),
                    dict(pid=waiter),
                )
            ).one()
            if (
                row.wait_event_type == "Lock"
                and blocker in row.blockers
                and row.ungranted
            ):
                return dict(
                    observer_pid=observer,
                    waiter_pid=waiter,
                    blocker_pid=blocker,
                    wait_type=row.wait_event_type,
                    ungranted=row.ungranted,
                )
            await asyncio.sleep(0.01)
    raise AssertionError(
        "Expected actual PostgreSQL writer wait was not observed"
    )


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == dict(detail=code)
    assert response.headers["cache-control"] == "no-store"


def observation(trace, *, platform, ordering, writer=None, wait=None):
    transaction = trace.only()
    if writer is not None:
        assert transaction["pid"] != writer
    return dict(
        platform=platform,
        ordering=ordering,
        actor_pid=transaction["pid"],
        writer_pid=writer,
        actor_index=transaction["actor_index"],
        settings=transaction["settings"],
        ended=transaction["ended"],
        sql=transaction["sql"],
        wait=wait,
        pid_source="psycopg_connection_info_backend_pid",
    )
