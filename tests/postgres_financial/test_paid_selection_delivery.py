"""Durable one-shot paid contact delivery with provider receipts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    capture_env,
    seed_creators,
    service,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    OrderItemModel,
    UserModel,
)

__all__ = ["capture_env"]


class Clock:
    def __init__(self):
        self.at = datetime.now(timezone.utc) + timedelta(seconds=1)

    def now(self):
        return self.at


class Bot:
    def __init__(self, env):
        self.env, self.calls, self.hook = env, [], None
        self.mode = "accepted"
        self.check_idle = True

    async def send_message(self, **payload):
        assert not self.check_idle or (
            self.env["container"].session_factory.kw["bind"].pool.checkedout()
            == 0
        )
        assert payload["parse_mode"] is None
        with Session(self.env["pg"]) as db:
            jobs = Base.metadata.tables["paid_selection_delivery_jobs"]
            attempts = Base.metadata.tables["paid_selection_delivery_attempts"]
            candidates = (
                db.execute(
                    select(jobs, attempts.c.source)
                    .join(
                        attempts,
                        jobs.c.current_attempt_id == attempts.c.attempt_id,
                    )
                    .where(
                        jobs.c.state == "sending",
                        attempts.c.text == payload["text"],
                    )
                )
                .mappings()
                .all()
            )
            # The scheduler can also process older valid synthetic orders.
            # Scope assertions/callbacks to this fixture's actual recipient.
            matching = [
                row
                for row in candidates
                if row["source"]["contact"]["address"]
                == str(payload["chat_id"])
            ]
            assert matching
            own = any(row["order_id"] == self.env["order"] for row in matching)
            if own:
                self.calls.append(payload)
            outcomes = Base.metadata.tables["paid_selection_delivery_outcomes"]
            assert all(
                db.scalar(
                    select(outcomes.c.outcome_id).where(
                        outcomes.c.attempt_id == row["current_attempt_id"],
                        outcomes.c.kind == "started",
                    )
                )
                for row in matching
            )
        if own and self.hook:
            await self.hook()
        if self.mode == "unknown":
            raise TimeoutError("synthetic provider ambiguity")
        if self.mode == "failed":
            from aiogram.exceptions import TelegramForbiddenError
            from aiogram.methods import SendMessage

            raise TelegramForbiddenError(
                method=SendMessage(
                    chat_id=payload["chat_id"], text=payload["text"]
                ),
                message="synthetic rejection",
            )
        return SimpleNamespace(
            message_id=7, chat=SimpleNamespace(id=payload["chat_id"])
        )


@pytest_asyncio.fixture
async def delivery_env(capture_env):
    env = capture_env
    creator, other_creator = seed_creators(env, count=2)
    await capture(env)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(telegram_id=str(uuid4().int % 10**12 + 1), language="ru")
        )
    interest = await service(env).respond(env["order"], creator)
    container = Container(
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "DATABASE_URL": env["pg"].url.render_as_string(
                    hide_password=False
                ),
                "DB_POOL_SIZE": 4,
                "FINANCIAL_CORE_ENABLED": True,
                "KAFKA_ENABLED": False,
                "USE_REDIS_STORAGE": False,
                "REDIS_URL": "",
            }
        )
    )
    env = env | {
        "creator": creator,
        "other_creator": other_creator,
        "interest": interest,
        "container": container,
    }
    bot = Bot(env)
    try:
        worker = container.build_paid_selection_delivery(bot)
        worker.clock = Clock()
        yield env | {"worker": worker, "bot": bot}
    finally:
        await container.dispose()


def rows(env, name):
    table = Base.metadata.tables[name]
    with Session(env["pg"]) as db:
        return (
            db.execute(select(table).where(table.c.order_id == env["order"]))
            .mappings()
            .all()
        )


def state(env):
    with Session(env["pg"]) as db:
        return db.get(
            OrderItemModel, env["interest"].paid_item_id
        ).selection_state


@pytest.mark.asyncio
async def test_actual_interest_delivers_once_with_committed_attempt(
    delivery_env,
):
    env = delivery_env
    assert state(env) == "paid"
    from ugc_bot.paid_selection_delivery_scheduler import run_loop

    await run_loop(env["worker"], max_iterations=1)
    await run_loop(env["worker"], max_iterations=1)
    assert await env["worker"].prepare(env["interest"].job_id) is None
    assert len(env["bot"].calls) == 1
    assert env["interest"].instagram_url in env["bot"].calls[0]["text"]
    assert state(env) == "delivered"
    (accepted,) = rows(env, "paid_selection_accepted_deliveries")
    assert accepted["paid_item_id"] == env["interest"].paid_item_id
    assert accepted["assignment_id"] == env["interest"].assignment_id
    assert (
        accepted["creator_id"] == env["creator"]
        and accepted["amount_minor"] == 50000
    )
    assert (
        accepted["payment_id"]
        and accepted["allocation_key"]
        and accepted["provider_reference"].endswith(":7")
    )
    # Provider acceptance creates no invented publication or financial maturity.
    assert not rows(env, "financial_collaborations")
    assert not rows(env, "financial_obligations")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failed", "unknown"])
async def test_provider_error_retains_interest_without_resending(
    delivery_env, mode
):
    env = delivery_env
    env["bot"].mode = mode
    await env["worker"].run_once()
    await env["worker"].run_once()
    assert len(env["bot"].calls) == 1 and state(env) == "paid"
    assert rows(env, "paid_selection_interests")[0]["accepted"] is True
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == mode
    assert rows(env, "paid_selection_accepted_deliveries") == []


@pytest.mark.asyncio
async def test_crashed_claim_recovers_unknown_without_sending(delivery_env):
    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    assert attempt and env["bot"].calls == []
    env["worker"].clock.at += timedelta(minutes=3)
    await env["worker"].run_once()
    assert env["bot"].calls == [] and state(env) == "paid"
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == "unknown"


@pytest.mark.asyncio
async def test_provider_accepted_null_reference_is_rejected_in_sql(
    delivery_env,
):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    table = Base.metadata.tables["paid_selection_delivery_outcomes"]
    with (
        pytest.raises(IntegrityError, match="ck_selection_provider_reference"),
        Session(env["pg"]) as db,
        db.begin(),
    ):
        db.execute(
            insert(table).values(
                outcome_id=uuid4(),
                job_id=attempt.job_id,
                order_id=attempt.order_id,
                attempt_id=attempt.attempt_id,
                kind="transport",
                status="accepted",
                recorded_at=env["worker"].clock.now(),
                provider_reference=None,
                reason=None,
                applied=False,
            )
        )
    assert state(env) == "paid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    ["contact", "client_role", "verification", "assignment", "deadline"],
)
async def test_source_change_before_send_cannot_count(delivery_env, changed):
    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    if changed == "assignment":
        from ugc_bot.infrastructure.db.repositories.item_assignments import (
            SqlAlchemyItemAssignmentRepository,
        )

        async with env["factory"].begin() as db:
            await SqlAlchemyItemAssignmentRepository().replace(
                paid_item_id=env["interest"].paid_item_id,
                expected_version=1,
                creator_id=env["creator"],
                manager_id=None,
                actor_id=env["client"],
                reason="explicit reassignment",
                at=env["worker"].clock.now(),
                session=db,
            )
    elif changed == "deadline":
        env["worker"].clock.at += timedelta(days=4)
    else:
        with Session(env["pg"]) as db, db.begin():
            if changed == "contact":
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == env["client"])
                    .values(telegram_id=str(uuid4().int % 10**12 + 1))
                )
            elif changed == "client_role":
                db.execute(
                    delete(AdvertiserProfileModel).where(
                        AdvertiserProfileModel.user_id == env["client"]
                    )
                )
            else:
                db.execute(
                    update(BloggerProfileModel)
                    .where(BloggerProfileModel.user_id == env["creator"])
                    .values(confirmed=False)
                )
    await env["worker"].deliver(attempt)
    assert env["bot"].calls == [] and state(env) == "paid"
    assert not rows(env, "paid_selection_accepted_deliveries")


@pytest.mark.asyncio
async def test_actual_accepted_stale_contact_is_retained_unapplied(
    delivery_env,
):
    env = delivery_env

    async def change():
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(telegram_id=str(uuid4().int % 10**12 + 1))
            )

    env["bot"].hook = change
    await env["worker"].run_once()
    assert len(env["bot"].calls) == 1 and state(env) == "paid"
    (outcome,) = [
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["kind"] == "transport"
    ]
    assert outcome["status"] == "accepted" and outcome[
        "provider_reference"
    ].endswith(":7")
    assert (
        not outcome["applied"]
        and outcome["reason"] == "selection_source_changed"
    )
    assert not rows(env, "paid_selection_accepted_deliveries")
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == "obsolete"


@pytest.mark.asyncio
async def test_forged_attempt_payload_never_reaches_transport(delivery_env):
    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    with pytest.raises(ValueError, match="selection_attempt_snapshot_invalid"):
        await env["worker"].deliver(
            replace(attempt, text="caller forged contact")
        )
    assert env["bot"].calls == [] and state(env) == "paid"


@pytest.mark.asyncio
async def test_concurrent_workers_send_one_committed_attempt(delivery_env):
    import asyncio

    env = delivery_env
    env[
        "bot"
    ].check_idle = False  # Another worker may own an unrelated session.
    await asyncio.wait_for(
        asyncio.gather(env["worker"].run_once(), env["worker"].run_once()),
        timeout=10,
    )
    assert len(env["bot"].calls) == 1 and state(env) == "delivered"
    assert len(rows(env, "paid_selection_delivery_attempts")) == 1
    assert len(rows(env, "paid_selection_accepted_deliveries")) == 1


@pytest.mark.asyncio
async def test_prepare_commit_failure_rolls_back_before_io(
    delivery_env, monkeypatch
):
    env = delivery_env
    repo = env["worker"].repository
    original = repo.save_job

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic_prepare_commit_failure")

    monkeypatch.setattr(repo, "save_job", fail)
    with pytest.raises(RuntimeError, match="synthetic_prepare_commit_failure"):
        await env["worker"].run_once()
    assert env["bot"].calls == []
    assert rows(env, "paid_selection_delivery_attempts") == []
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == "ready"
    monkeypatch.setattr(repo, "save_job", original)
    await env["worker"].run_once()
    assert state(env) == "delivered"


@pytest.mark.asyncio
async def test_finish_rollback_recovers_unknown_without_repeating_io(
    delivery_env, monkeypatch
):
    env = delivery_env
    repo = env["worker"].repository
    original = repo.accept

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic_finish_commit_failure")

    monkeypatch.setattr(repo, "accept", fail)
    with pytest.raises(RuntimeError, match="synthetic_finish_commit_failure"):
        await env["worker"].run_once()
    assert len(env["bot"].calls) == 1 and state(env) == "paid"
    assert not rows(env, "paid_selection_accepted_deliveries")
    assert not [
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["kind"] == "transport"
    ]
    env["worker"].clock.at += timedelta(minutes=3)
    monkeypatch.setattr(repo, "accept", original)
    await env["worker"].run_once()
    assert len(env["bot"].calls) == 1
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == "unknown"


@pytest.mark.asyncio
async def test_sibling_projection_correction_preserves_target_funding(
    delivery_env,
):
    env = delivery_env
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderItemModel)
            .where(
                OrderItemModel.order_id == env["order"],
                OrderItemModel.paid_item_id != env["interest"].paid_item_id,
            )
            .values(selection_state="refunded")
        )
    # This synthetic sibling projection is not a refund authorization or result.
    await env["worker"].run_once()
    assert state(env) == "delivered" and len(env["bot"].calls) == 1


@pytest.mark.asyncio
async def test_forged_job_pointer_has_no_send_or_acceptance(delivery_env):
    env = delivery_env
    jobs = Base.metadata.tables["paid_selection_delivery_jobs"]
    forged = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(jobs)
            .where(jobs.c.job_id == env["interest"].job_id)
            .values(job_id=forged)
        )
    assert await env["worker"].prepare(forged) is None
    assert env["bot"].calls == [] and state(env) == "paid"
    assert not rows(env, "paid_selection_accepted_deliveries")
    assert (
        rows(env, "paid_selection_delivery_outcomes")[0]["reason"]
        == "selection_delivery_pointer_invalid"
    )


@pytest.mark.asyncio
async def test_receipt_history_is_immutable_and_rebuilt_factory_does_not_resend(
    delivery_env,
):
    from sqlalchemy.exc import IntegrityError

    env = delivery_env
    await env["worker"].run_once()
    for name in (
        "paid_selection_delivery_attempts",
        "paid_selection_delivery_outcomes",
        "paid_selection_accepted_deliveries",
    ):
        for operation in (
            f"UPDATE {name} SET order_id=order_id",
            f"DELETE FROM {name}",
            f"TRUNCATE {name} CASCADE",
        ):
            with (
                pytest.raises(
                    IntegrityError, match="paid_selection_delivery_immutable"
                ),
                Session(env["pg"]) as db,
                db.begin(),
            ):
                db.execute(text(operation))
    other = Container(env["container"]._config)
    try:
        await other.build_paid_selection_delivery(env["bot"]).run_once()
    finally:
        await other.dispose()
    assert len(env["bot"].calls) == 1 and state(env) == "delivered"


@pytest.mark.asyncio
async def test_one_provider_reference_cannot_prove_two_paid_contacts(
    delivery_env,
):
    env = delivery_env
    await env["worker"].run_once()
    second = await service(env).respond(env["order"], env["other_creator"])
    assert second.accepted
    # A stale chat/message receipt cannot prove two distinct contacts.
    await env["worker"].run_once()
    assert len(env["bot"].calls) == 2
    assert len(rows(env, "paid_selection_accepted_deliveries")) == 1
    outcome = next(
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["job_id"] == second.job_id and r["kind"] == "transport"
    )
    assert outcome["status"] == "accepted" and not outcome["applied"]
    assert outcome["reason"] == "selection_provider_receipt_reused"


def test_empty_delivery_schema_can_round_trip():
    import os

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from tests.helpers.financial_environment import isolated_financial_database
    from ugc_bot.infrastructure.db.migrations.versions import (
        paid_selection_delivery_v1,
    )

    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="paid_selection_delivery_v1",
        ) as engine,
        engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        paid_selection_delivery_v1.downgrade()
        assert (
            "paid_selection_delivery_attempts"
            not in inspect(db).get_table_names()
        )
        paid_selection_delivery_v1.upgrade()
        assert (
            "paid_selection_accepted_deliveries"
            in inspect(db).get_table_names()
        )


@pytest.mark.asyncio
async def test_populated_delivery_schema_cannot_drop_history(delivery_env):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import (
        paid_selection_delivery_v1,
    )

    env = delivery_env
    await env["worker"].prepare(env["interest"].job_id)
    with (
        pytest.raises(RuntimeError, match="Cannot discard"),
        env["pg"].begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        paid_selection_delivery_v1.downgrade()
    assert len(rows(env, "paid_selection_delivery_attempts")) == 1


@pytest.mark.asyncio
async def test_waiting_across_deadline_never_starts_provider_io(
    delivery_env, monkeypatch
):
    env = delivery_env
    worker = env["worker"]
    with Session(env["pg"]) as db:
        due = db.get(
            OrderItemModel, env["interest"].paid_item_id
        ).selection_due_at
    worker.clock.at = due - timedelta(seconds=1)
    attempt = await worker.prepare(env["interest"].job_id)
    original = worker.repository.lock_source

    async def waited(*args, **kwargs):
        source = await original(*args, **kwargs)
        worker.clock.at = due + timedelta(seconds=1)
        return source

    monkeypatch.setattr(worker.repository, "lock_source", waited)
    await worker.deliver(attempt)
    assert env["bot"].calls == [] and state(env) == "paid"
    assert not rows(env, "paid_selection_accepted_deliveries")


@pytest.mark.asyncio
async def test_missing_job_and_contact_never_dispatch(delivery_env):
    env = delivery_env
    assert await env["worker"].prepare(uuid4()) is None
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(telegram_id=None)
        )
    await env["worker"].run_once()
    assert env["bot"].calls == [] and state(env) == "paid"
    assert (
        rows(env, "paid_selection_delivery_outcomes")[0]["reason"]
        == "selection_client_contact_unavailable"
    )


@pytest.mark.asyncio
async def test_unsafe_legacy_profile_url_is_not_sent(delivery_env):
    env = delivery_env
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == env["other_creator"])
            .values(instagram_url="https://evil.test/unsafe")
        )
    second = await service(env).respond(env["order"], env["other_creator"])
    assert await env["worker"].prepare(second.job_id) is None
    assert env["bot"].calls == []
    outcome = next(
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["job_id"] == second.job_id
    )
    assert outcome["reason"] == "selection_instagram_url_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["lease", "started"])
async def test_lost_fence_or_started_attempt_never_repeats_io(
    delivery_env, lost
):
    env = delivery_env
    attempt = await env["worker"].prepare(env["interest"].job_id)
    if lost == "started":
        assert await env["worker"]._begin(attempt)
    else:
        jobs = Base.metadata.tables["paid_selection_delivery_jobs"]
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(jobs)
                .where(jobs.c.job_id == attempt.job_id)
                .values(lease_token=uuid4())
            )
    await env["worker"].deliver(attempt)
    assert env["bot"].calls == [] and state(env) == "paid"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["receipt", "exception"])
async def test_malformed_transport_boundary_stays_unknown(
    delivery_env, invalid
):
    from unittest.mock import AsyncMock

    from ugc_bot.application.notice_delivery_ports import DeliveryReceipt

    env = delivery_env
    send = (
        AsyncMock(return_value=DeliveryReceipt("max", "wrong-channel"))
        if invalid == "receipt"
        else AsyncMock(side_effect=RuntimeError("private transport internals"))
    )
    env["worker"].transport = SimpleNamespace(send=send)
    await env["worker"].run_once()
    own_calls = [
        call
        for call in send.await_args_list
        if call.args[0].job_id == env["interest"].job_id
    ]
    assert len(own_calls) == 1 and state(env) == "paid"
    assert rows(env, "paid_selection_delivery_jobs")[0]["state"] == "unknown"
    (outcome,) = [
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["kind"] == "transport"
    ]
    assert outcome["status"] == "unknown" and "private" not in outcome["reason"]


@pytest.mark.asyncio
async def test_scope_retry_rolls_back_without_obsoleting_interest(
    delivery_env, monkeypatch
):
    env = delivery_env

    async def changed(*args, **kwargs):
        raise ValueError("selection_scope_changed_retry_required")

    monkeypatch.setattr(env["worker"].repository, "lock_source", changed)
    with pytest.raises(
        ValueError, match="selection_scope_changed_retry_required"
    ):
        await env["worker"].prepare(env["interest"].job_id)
    assert (
        env["bot"].calls == []
        and rows(env, "paid_selection_delivery_jobs")[0]["state"] == "ready"
    )


@pytest.mark.asyncio
async def test_finish_replay_preserves_actual_provider_receipt(delivery_env):
    env = delivery_env
    worker = env["worker"]
    attempt = await worker.prepare(env["interest"].job_id)
    await worker.deliver(attempt)
    (outcome,) = [
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["kind"] == "transport"
    ]
    await worker._finish(
        attempt, "accepted", outcome["provider_reference"], None
    )
    with pytest.raises(ValueError, match="selection_outcome_conflict"):
        await worker._finish(attempt, "accepted", "different-result", None)
    assert len(rows(env, "paid_selection_accepted_deliveries")) == 1


@pytest.mark.asyncio
async def test_accepted_result_after_fence_loss_stays_in_history(delivery_env):
    env = delivery_env
    jobs = Base.metadata.tables["paid_selection_delivery_jobs"]

    async def fence_changed():
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(jobs)
                .where(jobs.c.job_id == env["interest"].job_id)
                .values(lease_token=uuid4())
            )

    env["bot"].hook = fence_changed
    await env["worker"].run_once()
    (outcome,) = [
        r
        for r in rows(env, "paid_selection_delivery_outcomes")
        if r["kind"] == "transport"
    ]
    assert outcome["status"] == "accepted" and not outcome["applied"]
    assert outcome["reason"] == "selection_fence_stale"
    assert state(env) == "paid" and not rows(
        env, "paid_selection_accepted_deliveries"
    )


@pytest.mark.asyncio
async def test_client_role_cannot_change_between_final_check_and_commit(
    delivery_env, monkeypatch
):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    env = delivery_env
    worker = env["worker"]
    original = worker.repository.accept
    engine = create_async_engine(env["pg"].url, pool_size=1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    started, removed = asyncio.Event(), asyncio.Event()
    deletion = None

    async def remove_role():
        async with factory.begin() as db:
            started.set()
            await db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == env["client"]
                )
            )
        removed.set()

    async def checked_accept(*args, **kwargs):
        nonlocal deletion
        deletion = asyncio.create_task(remove_role())
        await started.wait()
        from contextlib import suppress

        with suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(removed.wait()), timeout=0.1)
        assert not removed.is_set()
        await original(*args, **kwargs)

    monkeypatch.setattr(worker.repository, "accept", checked_accept)
    try:
        await worker.run_once()
        assert len(rows(env, "paid_selection_accepted_deliveries")) == 1
    finally:
        if deletion is not None:
            await asyncio.wait_for(deletion, timeout=5)
        await engine.dispose()
    assert removed.is_set()


@pytest.mark.asyncio
async def test_profile_writer_before_row_lock_cannot_deadlock_preparation(
    delivery_env,
):
    import asyncio

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.identity_history_schema import (
        HISTORY_WRITER_LOCK_SQL,
    )

    env = delivery_env
    engine = create_async_engine(env["pg"].url, pool_size=1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    writer_locked, worker_waiting, update_allowed = (
        asyncio.Event() for _ in range(3)
    )
    worker_engine = env["container"].session_factory.kw["bind"].sync_engine

    def waiting(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock_shared(2119754201, 170434819)" in statement:
            worker_waiting.set()

    async def writer():
        async with factory.begin() as db:
            # Reproduce the actual BEFORE STATEMENT trigger order, paused
            # immediately before the UPDATE acquires the profile row lock.
            await db.execute(text(HISTORY_WRITER_LOCK_SQL))
            writer_locked.set()
            await update_allowed.wait()
            await db.execute(
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == env["creator"])
                .values(phone="+7 111 222 3333")
            )

    event.listen(worker_engine, "before_cursor_execute", waiting)
    task = asyncio.create_task(writer())
    preparation = None
    try:
        await asyncio.wait_for(writer_locked.wait(), timeout=5)
        preparation = asyncio.create_task(
            env["worker"].prepare(env["interest"].job_id)
        )
        await asyncio.wait_for(worker_waiting.wait(), timeout=5)
        update_allowed.set()
        _, attempt = await asyncio.wait_for(
            asyncio.gather(task, preparation), timeout=10
        )
        assert "+7 111 222 3333" in attempt.text
        await env["worker"].deliver(attempt)
        assert state(env) == "delivered"
    finally:
        update_allowed.set()
        await asyncio.gather(
            task,
            *([preparation] if preparation else []),
            return_exceptions=True,
        )
        event.remove(worker_engine, "before_cursor_execute", waiting)
        await engine.dispose()
