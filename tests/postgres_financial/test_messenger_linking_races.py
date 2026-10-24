"""Distinct PostgreSQL sessions prove lock order and post-wait clocks."""

import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from tests.postgres_financial.test_messenger_linking_repository import (
    link_env as _link_env,
)
from tests.postgres_financial.test_messenger_linking_repository import proposed
from ugc_bot.infrastructure.db.models import AdvertiserProfileModel, UserModel


@pytest_asyncio.fixture
async def link_env(financial_pg_engine):
    async for env in _link_env.__wrapped__(financial_pg_engine):
        yield env


async def wait_lock(engine, pid):
    for _ in range(100):
        async with engine.connect() as connection:
            blocked = await connection.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid))>0"),
                {"pid": pid},
            )
        if blocked:
            return
        await asyncio.sleep(0.01)
    pytest.fail("expected a real PostgreSQL lock wait")


@pytest.mark.asyncio
async def test_owner_lock_precedes_fk_holder_role_delete(link_env, monkeypatch):
    env = link_env
    view, _, _ = await proposed(env)
    owner_entered = asyncio.Event()
    started = asyncio.Future()
    original = env["repo"]._owner

    async def observe(actor, db):
        pid = await db.scalar(text("SELECT pg_backend_pid()"))
        if not started.done():
            started.set_result(pid)
        value = await original(actor, db)
        owner_entered.set()
        return value

    monkeypatch.setattr(env["repo"], "_owner", observe)
    blocker = env["transactions"]._session_factory()
    await blocker.begin()
    blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
    await blocker.execute(
        select(UserModel.user_id)
        .where(UserModel.user_id == env["actor"].user_id)
        .with_for_update(read=True, key_share=True)
    )
    task = asyncio.create_task(
        env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        )
    )
    try:
        pid = await asyncio.wait_for(started, 2)
        assert pid != blocker_pid
        await wait_lock(env["engine"], pid)
        assert not owner_entered.is_set(), (
            "late User lock upgrade retained role locks "
            "while waiting on FK holder"
        )
        await blocker.execute(
            delete(AdvertiserProfileModel).where(
                AdvertiserProfileModel.user_id == env["actor"].user_id
            )
        )
        await blocker.commit()
        result = await asyncio.wait_for(task, 3)
        assert result.state == "unavailable"
        assert (
            await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
        ).telegram_id is None
    finally:
        await blocker.rollback()
        await blocker.close()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("operation", ["create", "confirm", "status", "native"])
@pytest.mark.asyncio
async def test_clock_is_read_after_actual_identity_wait(
    link_env, monkeypatch, operation
):
    from tests.postgres_financial.test_messenger_linking_repository import (
        proposal,
    )
    from ugc_bot.infrastructure.db.repositories.messenger_linking import (
        acquire_link_identity_barrier,
    )

    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    if operation == "confirm":
        await env["service"].propose_native(proposal(waiting))
        waiting = await env["service"].status(env["actor"])
    started = asyncio.Future()
    original = env["repo"]._owner

    async def observe(actor, db):
        pid = await db.scalar(text("SELECT pg_backend_pid()"))
        if not started.done():
            started.set_result(pid)
        return await original(actor, db)

    monkeypatch.setattr(env["repo"], "_owner", observe)
    blocker = env["transactions"]._session_factory()
    await blocker.begin()
    blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
    await acquire_link_identity_barrier(blocker)
    if operation == "create":
        # Force a new actual issuance after old expiry.
        action = env["service"].create(env["actor"], "after-wait")
    elif operation == "confirm":
        action = env["service"].confirm(
            env["actor"],
            waiting.challenge_id,
            waiting.claim_id,
            waiting.version,
            "confirm",
        )
    elif operation == "status":
        action = env["service"].status(env["actor"])
    else:
        action = env["service"].propose_native(proposal(waiting))
    task = asyncio.create_task(action)
    try:
        pid = await asyncio.wait_for(started, 2)
        assert pid != blocker_pid
        await wait_lock(env["engine"], pid)
        env["clock"].value += timedelta(seconds=601)
        await blocker.commit()
        if operation == "confirm":
            with pytest.raises(ValueError, match="link_not_confirmable"):
                await asyncio.wait_for(task, 3)
        else:
            result = await asyncio.wait_for(task, 3)
            assert result.state == (
                "waiting" if operation == "create" else "expired"
            )
            if operation == "create":
                assert result.expires_at == env["clock"].value + timedelta(
                    seconds=600
                )
                assert result.challenge_id != waiting.challenge_id
        assert (
            await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
        ).telegram_id is None
    finally:
        await blocker.rollback()
        await blocker.close()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_owner_quota_window_uses_clock_after_user_wait(
    link_env, monkeypatch
):
    env = link_env
    for number in range(5):
        view = await env["service"].create(env["actor"], f"issue-{number}")
        await env["service"].revoke(
            env["actor"], view.challenge_id, view.version, f"revoke-{number}"
        )
    env["clock"].value += timedelta(seconds=3599)
    started = asyncio.Future()
    original = env["repo"]._owner

    async def observe(actor, db):
        if not started.done():
            started.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
        return await original(actor, db)

    monkeypatch.setattr(env["repo"], "_owner", observe)
    blocker = env["transactions"]._session_factory()
    await blocker.begin()
    await blocker.execute(
        select(UserModel.user_id)
        .where(UserModel.user_id == env["actor"].user_id)
        .with_for_update()
    )
    task = asyncio.create_task(
        env["service"].create(env["actor"], "new-window")
    )
    try:
        await wait_lock(env["engine"], await asyncio.wait_for(started, 2))
        env["clock"].value += timedelta(seconds=2)
        await blocker.commit()
        view = await asyncio.wait_for(task, 3)
        assert view.state == "waiting"
        assert view.expires_at == env["clock"].value + timedelta(seconds=600)
    finally:
        await blocker.rollback()
        await blocker.close()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_two_clicks_same_owner_create_one_active_challenge(
    link_env, monkeypatch
):
    env = link_env
    pids = set()
    original = env["repo"]._owner

    async def observe(actor, db):
        pids.add(await db.scalar(text("SELECT pg_backend_pid()")))
        return await original(actor, db)

    monkeypatch.setattr(env["repo"], "_owner", observe)
    one, two = await asyncio.gather(
        env["service"].create(env["actor"], "click-one"),
        env["service"].create(env["actor"], "click-two"),
    )
    assert len(pids) >= 2
    assert (
        one.challenge_id == two.challenge_id
        and one.launch_url == two.launch_url
    )


@pytest.mark.asyncio
async def test_two_native_claimants_cannot_replace_first_proposal(link_env):
    from tests.postgres_financial.test_messenger_linking_repository import (
        proposal,
    )

    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    one, two = await asyncio.gather(
        env["service"].propose_native(proposal(waiting)),
        env["service"].propose_native(proposal(waiting)),
    )
    assert sorted([one.state, two.state]) == ["conflict", "proposed"]
    view = await env["service"].status(env["actor"])
    assert view.claim_id in {one.claim_id, two.claim_id}
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_confirm_and_revoke_have_one_winner_without_partial_attach(
    link_env,
):
    env = link_env
    view, native, _ = await proposed(env)
    results = await asyncio.gather(
        env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        ),
        env["service"].revoke(
            env["actor"], view.challenge_id, view.version, "revoke"
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(value, Exception) for value in results) == 1
    current = await env["service"].status(env["actor"])
    user = await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    assert current.state in {"linked", "revoked"}
    assert user.telegram_id == (
        native.sender_id if current.state == "linked" else None
    )


@pytest.mark.parametrize("signup_commits", [True, False])
@pytest.mark.asyncio
async def test_real_registration_race_never_reassigns_or_attaches_expired_proof(
    link_env, monkeypatch, signup_commits
):
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from ugc_bot.domain.enums import MessengerType

    env = link_env
    view, native, _ = await proposed(env)
    inserted = asyncio.Event()
    release = asyncio.Event()
    confirmer_pid = asyncio.Future()
    original = env["repo"]._owner

    class SignupTransaction:
        @asynccontextmanager
        async def transaction(self):
            async with env["transactions"].transaction() as db:
                yield db
                await db.flush()
                inserted.set()
                await release.wait()
                if not signup_commits:
                    raise RuntimeError("synthetic registration rollback")

    async def observe(actor, db):
        if not confirmer_pid.done():
            confirmer_pid.set_result(
                await db.scalar(text("SELECT pg_backend_pid()"))
            )
        return await original(actor, db)

    roles = replace(
        env["container"].build_bot_services()["user_role_service"],
        transaction_manager=SignupTransaction(),
    )
    signup = asyncio.create_task(
        roles.set_user(
            native.sender_id, MessengerType.TELEGRAM, "Actual signup"
        )
    )
    await asyncio.wait_for(inserted.wait(), 3)
    monkeypatch.setattr(env["repo"], "_owner", observe)
    confirm = asyncio.create_task(
        env["service"].confirm(
            env["actor"], view.challenge_id, view.claim_id, view.version, "race"
        )
    )
    try:
        pid = await asyncio.wait_for(confirmer_pid, 3)
        await wait_lock(env["engine"], pid)
        if not signup_commits:
            env["clock"].value += timedelta(seconds=601)
        release.set()
        if signup_commits:
            registered = await asyncio.wait_for(signup, 3)
            result = await asyncio.wait_for(confirm, 3)
            assert result.state == "conflict"
            assert registered.user_id != env["actor"].user_id
            assert (
                await env["repos"]["user_repo"].get_by_external(
                    native.sender_id, MessengerType.TELEGRAM
                )
            ).user_id == registered.user_id
        else:
            with pytest.raises(RuntimeError, match="registration rollback"):
                await asyncio.wait_for(signup, 3)
            with pytest.raises(ValueError, match="link_not_confirmable"):
                await asyncio.wait_for(confirm, 3)
            assert (
                await env["repos"]["user_repo"].get_by_external(
                    native.sender_id, MessengerType.TELEGRAM
                )
                is None
            )
        assert (
            await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
        ).telegram_id is None
    finally:
        release.set()
        await asyncio.gather(signup, confirm, return_exceptions=True)
