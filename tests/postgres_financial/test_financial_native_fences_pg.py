"""Real User barriers keep financial native authority stable until commit."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)
from tests.postgres_financial.test_payout_runtime import (
    request_command,
    review_command,
    rows,
)
from tests.postgres_financial.test_rate_override_persistence import (
    command as override_command,
)
from tests.postgres_financial.test_rate_override_persistence import (
    override_pg as override_pg,
)
from tests.postgres_financial.test_work_entitlement_runtime import wallet
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.override_models import COMMANDS, EVENTS

__all__ = ["capture_env", "payout_env", "override_pg"]

PAYOUT_OPERATIONS = ("request", "replay", "review", "reveal", "recovery")
OVERRIDE_OPERATIONS = ("execute", "replay", "get", "list")


@pytest.fixture(scope="session")
def native_evidence():
    records = []
    yield records
    path = os.environ.get("FINANCIAL_NATIVE_EVIDENCE_PATH")
    if path:
        Path(path).write_text(json.dumps(records, indent=2) + "\n")


@pytest_asyncio.fixture
async def native_factory(financial_pg_engine):
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=4, max_overflow=0
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def pid(db):
    await db.execute(text("SET LOCAL statement_timeout='5s'"))
    await db.execute(text("SET LOCAL lock_timeout='4s'"))
    return await db.scalar(text("SELECT pg_backend_pid()"))


async def wait_blocked(observer, waiting, blocker):
    for _ in range(150):
        blockers = await observer.scalar(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting}
        )
        if blocker in blockers:
            return
        await asyncio.sleep(0.01)
    pytest.fail("financial User barrier did not produce the expected PID wait")


def set_native(env, uid):
    telegram, maximum = (str(uuid4().int % 10**14 + 1) for _ in range(2))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == uid)
            .values(telegram_id=telegram, max_id=maximum)
        )
    return telegram, maximum


def principal(uid, platform, native):
    return AuthenticatedMessengerPrincipal(
        uid, platform, native[platform == "max"]
    )


def money_and_facts(env):
    return (
        dict(wallet(env, env["flow"]["manager"])),
        {
            name: [dict(r) for r in rows(env, name)]
            for name in (
                "commands",
                "requests",
                "events",
                "intents",
                "outcomes",
                "settlements",
                "requisites",
            )
        },
    )


async def payout_call(env, operation, platform):
    owner, admin = env["flow"]["manager"], env["client"]
    actor = admin if operation in ("review", "reveal") else owner
    native = set_native(env, actor)
    proof = principal(actor, platform, native)
    cmd = request_command(env)
    state = None
    if operation != "request":
        state = await env["execute"](cmd)

    async def call(db):
        service = env["service"]
        if operation in ("request", "replay"):
            return await service.execute(cmd, session=db, principal=proof)
        if operation == "review":
            return await service.execute(
                review_command(env, state, "review"),
                session=db,
                principal=proof,
            )
        if operation == "reveal":
            return await service.reveal_for_admin(
                state["request_id"],
                actor,
                operation_key="synthetic-native-reveal:" + str(uuid4()),
                reason="Synthetic native authorization audit",
                session=db,
                principal=proof,
            )
        return await service.operation_for_actor(
            actor, cmd.operation_key, session=db, principal=proof
        )

    scope = (actor, owner) if operation in ("review", "reveal") else (actor,)
    return actor, proof, scope, call


async def override_call(override_pg, operation, platform):
    factory, repo, service, _, data = override_pg
    native = tuple(str(uuid4().int % 10**14 + 1) for _ in range(2))
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == data["admin"])
            .values(telegram_id=native[0], max_id=native[1])
        )
    proof = principal(data["admin"], platform, native)
    cmd = override_command(data)
    first = None
    if operation != "execute":
        async with factory.begin() as db:
            first = await service.execute(cmd, session=db, principal=proof)

    async def call(db):
        if operation in ("execute", "replay"):
            return await service.execute(cmd, session=db, principal=proof)
        if operation == "get":
            return await service.get_for_admin(
                first.override.approval.override_id,
                actor_id=data["admin"],
                session=db,
                principal=proof,
            )
        return await service.list_for_admin(
            data["recipient"],
            "creator",
            data["policy"],
            actor_id=data["admin"],
            session=db,
            principal=proof,
        )

    scope = (
        (data["admin"],)
        if operation == "get"
        else (data["admin"], data["recipient"])
    )
    return data["admin"], proof, scope, call


@asynccontextmanager
async def observed_users(factory):
    """Record actual locked SELECT order on only the service connection."""
    engine = factory.kw["bind"]
    locked = []

    def before(conn, cursor, statement, parameters, context, many):
        if (
            conn.info.get("native_fence_reader")
            and "FROM users" in statement
            and "FOR NO KEY UPDATE" in statement
        ):
            locked.append(parameters["user_id_1"])

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield locked
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def remap_before_barrier(
    factory, actor, proof, scope, call, change, evidence, label
):
    started = asyncio.Future()

    async def invoke():
        async with factory.begin() as db:
            reader_pid = await pid(db)
            connection = await db.connection()
            connection.info["native_fence_reader"] = True
            started.set_result(reader_pid)
            try:
                with pytest.raises(
                    ValueError, match="^financial_principal_changed$"
                ):
                    await call(db)
            finally:
                connection.info.pop("native_fence_reader", None)

    task = None
    async with observed_users(factory) as locked:
        async with factory.begin() as writer:
            writer_pid = await pid(writer)
            field = "telegram_id" if proof.platform == "telegram" else "max_id"
            await writer.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(
                    **{field: None if change == "clear" else str(uuid4().int)}
                )
            )
            task = asyncio.create_task(invoke())
            try:
                reader_pid = await asyncio.wait_for(started, 2)
                assert reader_pid != writer_pid
                await wait_blocked(writer, reader_pid, writer_pid)
                assert not task.done()
                await writer.commit()
                await asyncio.wait_for(task, 3)
            finally:
                await writer.rollback()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        expected = tuple(sorted(set(scope), key=str))
        assert tuple(locked) == expected
    async with factory.begin() as db:
        user = (
            (
                await db.execute(
                    select(UserModel.__table__).where(
                        UserModel.user_id == actor
                    )
                )
            )
            .mappings()
            .one()
        )
        assert user["status"] == "active"
        if len(set(scope)) > 1 or label.startswith("override:"):
            assert user["admin"] is True
    evidence.append(
        dict(
            case=label,
            direction="mapping_commit_before_barrier",
            platform=proof.platform,
            change=change,
            reader_pid=reader_pid,
            writer_pid=writer_pid,
            user_order=[str(u) for u in expected],
            completed=True,
        )
    )


async def update_after_authorization(
    factory, actor, proof, call, evidence, label
):
    started = asyncio.Future()

    async def change():
        async with factory.begin() as db:
            writer_pid = await pid(db)
            started.set_result(writer_pid)
            field = "telegram_id" if proof.platform == "telegram" else "max_id"
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(**{field: None})
            )

    async with factory.begin() as reader:
        reader_pid = await pid(reader)
        result = await call(reader)
        assert result is not None
        if label == "payout:review":
            assert result["state"] == "approved"
        task = asyncio.create_task(change())
        try:
            writer_pid = await asyncio.wait_for(started, 2)
            assert writer_pid != reader_pid
            await wait_blocked(reader, writer_pid, reader_pid)
            assert not task.done()
            await reader.commit()
            await asyncio.wait_for(task, 3)
        finally:
            await reader.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    evidence.append(
        dict(
            case=label,
            direction="native_update_waits_for_financial_commit",
            platform=proof.platform,
            reader_pid=reader_pid,
            writer_pid=writer_pid,
            completed=True,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["remap", "clear"])
@pytest.mark.parametrize("operation", PAYOUT_OPERATIONS)
async def test_payout_mapping_commit_is_checked_at_actual_user_barrier(
    payout_env, native_factory, native_evidence, platform, change, operation
):
    actor, proof, scope, call = await payout_call(
        payout_env, operation, platform
    )
    before = money_and_facts(payout_env)
    await remap_before_barrier(
        native_factory,
        actor,
        proof,
        scope,
        call,
        change,
        native_evidence,
        "payout:" + operation,
    )
    assert money_and_facts(payout_env) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["remap", "clear"])
@pytest.mark.parametrize("operation", OVERRIDE_OPERATIONS)
async def test_override_mapping_commit_is_checked_at_actual_user_barrier(
    override_pg, native_evidence, platform, change, operation
):
    actor, proof, scope, call = await override_call(
        override_pg, operation, platform
    )
    factory, repo, _, _, data = override_pg
    async with factory.begin() as db:
        counts = tuple(
            [
                await db.scalar(select(func.count()).select_from(table))
                for table in (COMMANDS, EVENTS)
            ]
        )
        before = await repo.list_scope(
            data["recipient"], "creator", data["policy"], session=db
        )
    await remap_before_barrier(
        factory,
        actor,
        proof,
        scope,
        call,
        change,
        native_evidence,
        "override:" + operation,
    )
    async with factory.begin() as db:
        assert (
            await repo.list_scope(
                data["recipient"], "creator", data["policy"], session=db
            )
            == before
        )
        assert (
            tuple(
                [
                    await db.scalar(select(func.count()).select_from(table))
                    for table in (COMMANDS, EVENTS)
                ]
            )
            == counts
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("operation", PAYOUT_OPERATIONS)
async def test_payout_user_barrier_blocks_native_update_until_transaction_ends(
    payout_env, native_factory, native_evidence, platform, operation
):
    actor, proof, _, call = await payout_call(payout_env, operation, platform)
    await update_after_authorization(
        native_factory,
        actor,
        proof,
        call,
        native_evidence,
        "payout:" + operation,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("operation", OVERRIDE_OPERATIONS)
async def test_override_barrier_blocks_native_update_until_commit(
    override_pg, native_evidence, platform, operation
):
    actor, proof, _, call = await override_call(
        override_pg, operation, platform
    )
    await update_after_authorization(
        override_pg[0],
        actor,
        proof,
        call,
        native_evidence,
        "override:" + operation,
    )


@pytest.mark.asyncio
async def test_actual_cross_platform_payout_replay_keeps_receipt_and_money(
    payout_env, native_factory
):
    env = payout_env
    actor = env["flow"]["manager"]
    native = set_native(env, actor)
    cmd = request_command(env)
    async with native_factory.begin() as db:
        first = await env["service"].execute(
            cmd, session=db, principal=principal(actor, "telegram", native)
        )
    before = money_and_facts(env)
    async with native_factory.begin() as db:
        assert (
            await env["service"].execute(
                cmd, session=db, principal=principal(actor, "max", native)
            )
            == first
        )
    assert money_and_facts(env) == before


@pytest.mark.asyncio
async def test_actual_uuid_and_current_admin_revocation_remain_independent(
    override_pg,
):
    actor, proof, _, call = await override_call(
        override_pg, "execute", "telegram"
    )
    factory, _, service, _, data = override_pg
    async with factory.begin() as db:
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            await service.execute(
                override_command(data),
                session=db,
                principal=replace(proof, user_id=uuid4()),
            )
    async with factory.begin() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == actor)
            .values(admin=False)
        )
    async with factory.begin() as db:
        with pytest.raises(ValueError, match="^active_admin_required$"):
            await call(db)


@pytest.mark.asyncio
async def test_actual_override_cross_platform_replay_preserves_original_receipt(
    override_pg,
):
    factory, repo, service, _, data = override_pg
    actor, proof, _, call = await override_call(
        override_pg, "execute", "telegram"
    )
    async with factory.begin() as db:
        first = await call(db)
        receipt = await repo.get_command(
            override_command(data).operation_key, session=db
        )
    async with factory.begin() as db:
        assert (
            await service.execute(
                override_command(data),
                session=db,
                principal=replace(
                    proof,
                    platform="max",
                    external_id=(
                        await db.scalar(
                            select(UserModel.max_id).where(
                                UserModel.user_id == actor
                            )
                        )
                    ),
                ),
            )
            == first
        )
        assert (
            await repo.get_command(
                override_command(data).operation_key, session=db
            )
            == receipt
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["uuid", "status", "admin"])
async def test_actual_payout_canonical_and_current_authority_are_required(
    payout_env, native_factory, case
):
    env = payout_env
    actor = env["flow"]["manager"]
    proof = principal(actor, "telegram", set_native(env, actor))
    cmd = request_command(env)
    expected = "financial_principal_changed"
    if case == "uuid":
        proof = replace(proof, user_id=uuid4())
    elif case == "status":
        expected = "active_actor_required"
        async with native_factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(status="blocked")
            )
    else:
        expected = "active_admin_required"
        async with native_factory.begin() as db:
            state = await env["service"].execute(
                cmd, session=db, principal=proof
            )
        actor = env["client"]
        proof = principal(actor, "max", set_native(env, actor))
        cmd = review_command(env, state, "review")
        async with native_factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == actor)
                .values(admin=False)
            )
    before = money_and_facts(env)
    async with native_factory.begin() as db:
        with pytest.raises(ValueError, match="^" + expected + "$"):
            await env["service"].execute(cmd, session=db, principal=proof)
    assert money_and_facts(env) == before
