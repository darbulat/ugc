"""Actual SQL fixtures and bounded scheduling for legacy confirmation tests."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4, uuid5

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import (
    build_instagram_verification_service,
)
from ugc_bot.domain.entities import BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.identity_history_models import (
    IDENTITY_OBSERVATIONS,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InstagramVerificationCodeModel,
    UserModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.infrastructure.db.social_models import SocialAccountModel
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInstagramGraphApiClient,
)


async def backend_pid(db):
    await db.execute(text("SET LOCAL statement_timeout='5s'"))
    await db.execute(text("SET LOCAL lock_timeout='4s'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def wait_for_blocker(observer, waiting, blocker):
    for _ in range(200):
        blockers = await observer.scalar(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting}
        )
        if blocker in blockers:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected independent PostgreSQL backend wait")


async def finish_tasks(*tasks):
    for task in tasks:
        if task is not None and not task.done():
            task.cancel()
    await asyncio.gather(
        *(task for task in tasks if task is not None), return_exceptions=True
    )


async def wait_for_signal(signal, producer):
    """Wait for readiness or producer failure within the test's deadline."""
    await asyncio.wait((signal, producer), return_when=asyncio.FIRST_COMPLETED)
    if producer.done():
        await producer
        raise AssertionError("confirmation_task_finished_before_boundary")
    return signal.result()


def user_fact(*, user_id=None, max_id=None, telegram_id=None):
    now = datetime.now(timezone.utc)
    uid = user_id or uuid4()
    return User(
        user_id=uid,
        messenger_type=MessengerType.TELEGRAM,
        username="original " + uid.hex[:8],
        status=UserStatus.ACTIVE,
        issue_count=7,
        created_at=now,
        updated_at=now,
        telegram_id=telegram_id or "tg_" + uid.hex,
        max_id=max_id,
        max_chat_id="old_chat" if max_id else None,
        role_chosen_at=now,
        admin=True,
        country="kazakhstan",
        language="kk",
    )


def profile_fact(user, *, phone=None, confirmed=False):
    now = datetime.now(timezone.utc)
    handle = "u" + uuid5(user.user_id, "legacy-confirmation").hex[:24]
    return BloggerProfile(
        user_id=user.user_id,
        instagram_url="https://instagram.com/" + handle,
        confirmed=confirmed,
        city="Almaty",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Almaty",
        price=1500,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        created_at=now,
        updated_at=now,
        instagram_user_id="initial_" + user.user_id.hex,
        instagram_username=handle,
        country="kazakhstan",
        currency="KZT",
        phone=phone,
    )


@dataclass
class LegacyConfirmationCase:
    factory: object = field(repr=False)
    repos: dict = field(repr=False)
    transactions: object = field(repr=False)
    service: object = field(repr=False)
    api: object = field(repr=False)
    target: User
    profile: BloggerProfile
    sender: str

    async def seed(self, user, profile=None):
        async with self.transactions.transaction() as db:
            await self.repos["user_repo"].save(user, session=db)
            if profile is not None:
                await self.repos["blogger_repo"].save(profile, session=db)

    async def code(self, **metadata):
        return await self.service.generate_code(self.target.user_id, **metadata)

    async def confirm(self, mode, code):
        if mode == "manual":
            return await self.service.verify_code(
                self.target.user_id, code.code
            )
        return await self.service.verify_code_by_instagram_sender(
            self.sender, code.code, "synthetic_admin"
        )

    async def facts(self, code, *, user_id=None):
        uid = user_id or self.target.user_id
        tables = {
            "user": (UserModel.__table__, UserModel.user_id == uid),
            "profile": (
                BloggerProfileModel.__table__,
                BloggerProfileModel.user_id == uid,
            ),
            "code": (
                InstagramVerificationCodeModel.__table__,
                InstagramVerificationCodeModel.code_id == code.code_id,
            ),
            "social": (
                SocialAccountModel.__table__,
                SocialAccountModel.user_id == uid,
            ),
            "history": (
                IDENTITY_OBSERVATIONS,
                IDENTITY_OBSERVATIONS.c.creator_user_id == uid,
            ),
        }
        async with self.factory.begin() as db:
            return {
                name: [
                    dict(row)
                    for row in (
                        await db.execute(
                            select(table)
                            .where(condition)
                            .order_by(*table.primary_key.columns)
                        )
                    ).mappings()
                ]
                for name, (table, condition) in tables.items()
            }


@asynccontextmanager
async def confirmation_case(private_engine):
    """No engine is created until the authorized PG fixture is invoked."""
    engine = create_async_engine(
        private_engine.url, pool_size=5, max_overflow=0
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repos = build_repos(
        factory, redis_url="redis://synthetic-verification.invalid/0"
    )
    transactions = SessionTransactionManager(factory)
    target = user_fact()
    profile = profile_fact(target)
    sender = "sender_" + target.user_id.hex
    api = InMemoryInstagramGraphApiClient(
        username_map={sender: profile.instagram_username}
    )
    service = build_instagram_verification_service(repos, api, transactions)
    case = LegacyConfirmationCase(
        factory, repos, transactions, service, api, target, profile, sender
    )
    try:
        await case.seed(target, profile)
        yield case
    finally:
        await engine.dispose()


class ObservedConfirmationTransaction:
    """Delegate actual SQL transactions and hold only the selected boundary."""

    def __init__(
        self, delegate, mode, *, started=None, completed=None, release=None
    ):
        self.delegate = delegate
        self.selected = 1 if mode == "manual" else 2
        self.count = 0
        self.started = started
        self.completed = completed
        self.release = release
        self.reader_pid = None

    @asynccontextmanager
    async def transaction(self):
        self.count += 1
        selected = self.count == self.selected
        async with self.delegate.transaction() as db:
            connection = None
            if selected:
                self.reader_pid = await backend_pid(db)
                connection = await db.connection()
                connection.info["legacy_confirmation_reader"] = self.reader_pid
                if self.started is not None:
                    self.started.set_result(self.reader_pid)
            try:
                yield db
                if selected and self.completed is not None:
                    self.completed.set_result(self.reader_pid)
                if selected and self.release is not None:
                    await self.release.wait()
            finally:
                if connection is not None:
                    connection.info.pop("legacy_confirmation_reader", None)


@asynccontextmanager
async def observe_confirmation_sql(case):
    """Observe real statements; never replace repository reads or writes."""
    engine = case.factory.kw["bind"].sync_engine
    records = []

    def before(conn, cursor, statement, parameters, context, many):
        reader = conn.info.get("legacy_confirmation_reader")
        if reader is None:
            return
        kind, uid = None, None
        if "FROM users" in statement and "FOR NO KEY UPDATE" in statement:
            kind, uid = "user", parameters["user_id_1"]
        elif "pg_advisory_xact_lock" in statement:
            kind = "history" if "2119754201" in statement else "native"
        elif (
            "FROM instagram_verification_codes" in statement
            and "FOR UPDATE" in statement
        ):
            kind = "code"
        elif "FROM blogger_profiles" in statement and "FOR UPDATE" in statement:
            kind = "profile"
        if kind is not None:
            records.append({"kind": kind, "user_id": uid, "pid": reader})

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield records
    finally:
        event.remove(engine, "before_cursor_execute", before)


def assert_barrier_order(records, users, *, native=True, confirmed=True):
    scope = tuple(sorted(set(users), key=str))
    first_downstream = next(
        (i for i, row in enumerate(records) if row["kind"] != "user"),
        len(records),
    )
    locked = tuple(row["user_id"] for row in records[:first_downstream])
    assert locked == scope
    assert all(
        row["user_id"] in scope for row in records if row["kind"] == "user"
    )
    kinds = [row["kind"] for row in records]
    if native:
        assert kinds[first_downstream] == "native"
    if confirmed:
        assert kinds.index("code") < kinds.index("history")
        assert kinds.index("history") < kinds.index("profile")
