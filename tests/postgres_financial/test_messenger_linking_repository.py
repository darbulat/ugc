"""Real attach-only facts, transaction rollback and safe source replay."""

import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_user,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.messenger_linking import MaxLinkActor, NativeLinkProposal
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.session import SessionTransactionManager


class Clock:
    def __init__(self):
        self.value = datetime.now(timezone.utc)

    def now(self):
        return self.value


@pytest_asyncio.fixture
async def link_env(financial_pg_engine):
    from ugc_bot.container.messenger_linking_factory import (
        build_messenger_linking_service,
    )

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "123:" + "A" * 35,
            "TELEGRAM_BOT_USERNAME": "synthetic_test_bot",
            "MAX_BOT_TOKEN": "synthetic-max-token",
            "WEBHOOK_SECRET": "synthetic-secret",
            "KAFKA_ENABLED": False,
            "REDIS_URL": "",
            "USE_REDIS_STORAGE": False,
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "MESSENGER_LINKING_ENABLED": True,
            "MESSENGER_LINKING_TOKEN_SECRET": base64.urlsafe_b64encode(
                b"s" * 32
            )
            .decode()
            .rstrip("="),
            "MESSENGER_LINKING_KEY_ID": "test-key",
        }
    )
    container = Container(config)
    repos = container.build_repos()
    user = await create_test_user(
        repos["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        messenger_type=MessengerType.MAX,
        country="ru",
        language="en",
        admin=True,
    )
    await create_test_advertiser_profile(repos["advertiser_repo"], user.user_id)
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=5, max_overflow=2
    )
    tm = SessionTransactionManager(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    service = build_messenger_linking_service(config, tm)
    clock = Clock()
    service.clock = clock
    try:
        yield dict(
            config=config,
            container=container,
            repos=repos,
            user=user,
            actor=MaxLinkActor(user.user_id, user.max_id),
            engine=engine,
            transactions=tm,
            service=service,
            repo=service.repository,
            clock=clock,
            pg=financial_pg_engine,
        )
    finally:
        await engine.dispose()
        await container.session_factory.kw["bind"].dispose()


def proposal(view, *, sender=None, source=None):
    return NativeLinkProposal(
        123,
        sender or str(uuid4().int % 10**12 + 1),
        source or str(uuid4().int % 10**12 + 1),
        "20",
        view.expires_at - timedelta(seconds=600),
        view.launch_url.split("start=", 1)[1],
        "<Actual TG>",
        "actual_tg",
    )


async def proposed(env, **changes):
    waiting = await env["service"].create(env["actor"], "issue-" + uuid4().hex)
    native = proposal(waiting, **changes)
    receipt = await env["service"].propose_native(native)
    return await env["service"].status(env["actor"]), native, receipt


def test_actual_migration_has_linking_facts(financial_pg_engine):
    names = set(inspect(financial_pg_engine).get_table_names())
    assert "messenger_link_challenges" in names
    assert "messenger_link_native_results" in names


@pytest.mark.asyncio
async def test_real_attach_preserves_uuid_and_canonical_fields(link_env):
    env = link_env
    before = await env["repos"]["user_repo"].get_by_id(env["user"].user_id)
    view, native, receipt = await proposed(env)
    assert receipt.state == "proposed"
    assert (await env["repos"]["user_repo"].get_by_id(before.user_id)) == before
    linked = await env["service"].confirm(
        env["actor"], view.challenge_id, view.claim_id, view.version, "confirm"
    )
    after = await env["repos"]["user_repo"].get_by_id(before.user_id)
    assert linked.state == "linked" and linked.launch_url is None
    assert after == replace(before, telegram_id=native.sender_id)
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(UserModel.user_id).where(
                    UserModel.telegram_id == native.sender_id
                )
            )
            == before.user_id
        )


@pytest.mark.asyncio
async def test_durable_facts_hide_bearer_and_rebuild_recovers_live_url(
    link_env,
):
    from ugc_bot.container.messenger_linking_factory import (
        build_messenger_linking_service,
    )
    from ugc_bot.infrastructure.db.messenger_linking_models import TABLES

    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    await env["service"].propose_native(proposal(waiting))
    with Session(env["pg"]) as db:
        material = json.dumps(
            {
                key: [dict(row) for row in db.execute(select(table)).mappings()]
                for key, table in TABLES.items()
            },
            default=str,
        )
    assert waiting.launch_url not in material
    assert waiting.launch_url.split("start=", 1)[1] not in material
    rebuilt = build_messenger_linking_service(
        env["config"], env["transactions"]
    )
    rebuilt.clock = env["clock"]
    assert (
        await rebuilt.create(env["actor"], "issue")
    ).launch_url == waiting.launch_url


@pytest.mark.asyncio
async def test_confirm_failure_after_user_update_rolls_back_all_facts(link_env):
    from ugc_bot.infrastructure.db.messenger_linking_models import (
        COMMANDS,
        STATE,
    )

    env = link_env
    view, native, _ = await proposed(env)

    def fail_command(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().startswith("INSERT INTO messenger_link_commands"):
            raise RuntimeError("injected after user CAS")

    event.listen(
        env["engine"].sync_engine, "before_cursor_execute", fail_command
    )
    try:
        with pytest.raises(RuntimeError, match="injected"):
            await env["service"].confirm(
                env["actor"],
                view.challenge_id,
                view.claim_id,
                view.version,
                "confirm",
            )
    finally:
        event.remove(
            env["engine"].sync_engine, "before_cursor_execute", fail_command
        )
    user = await env["repos"]["user_repo"].get_by_id(env["user"].user_id)
    assert user.telegram_id is None
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(STATE.c.state).where(
                    STATE.c.challenge_id == view.challenge_id
                )
            )
            == "proposed"
        )
        assert (
            db.scalar(
                select(COMMANDS.c.command_id).where(
                    COMMANDS.c.owner_id == user.user_id,
                    COMMANDS.c.operation_key == "confirm",
                )
            )
            is None
        )
    assert (
        await env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        )
    ).state == "linked"


@pytest.mark.asyncio
async def test_separately_registered_target_is_conflict_and_no_detach(link_env):
    env = link_env
    other = await create_test_user(
        env["repos"]["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    other = await env["repos"]["user_repo"].get_by_id(other.user_id)
    waiting = await env["service"].create(env["actor"], "issue")
    result = await env["service"].propose_native(
        proposal(waiting, sender=other.telegram_id)
    )
    assert result.state == "conflict"
    assert (await env["service"].status(env["actor"])).state == "conflict"
    assert await env["repos"]["user_repo"].get_by_id(other.user_id) == other
    assert (
        await env["repos"]["user_repo"].get_by_id(env["user"].user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_actual_legacy_attachment_conflict_preserves_original_challenge(
    link_env,
):
    env = link_env
    view, _, _ = await proposed(env)
    target = await create_test_user(
        env["repos"]["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    handle = "legacy_" + uuid4().hex[:20]
    await create_test_blogger_profile(
        env["repos"]["blogger_repo"],
        target.user_id,
        instagram_url="https://instagram.com/" + handle,
        confirmed=False,
    )
    role_service = env["container"].build_bot_services()["user_role_service"]
    before_old = await env["repos"]["user_repo"].get_by_id(env["user"].user_id)
    before_new = await env["repos"]["user_repo"].get_by_id(target.user_id)
    attachment = await role_service.link_max_account(
        env["actor"].external_id,
        "https://instagram.com/" + handle,
        "legacy_remap",
    )
    assert attachment.state == "conflict"
    assert attachment.reason == "separate_canonical_owner"
    assert (await env["service"].status(env["actor"])) == view
    assert (
        await env["repos"]["user_repo"].get_by_id(before_old.user_id)
        == before_old
    )
    assert (
        await env["repos"]["user_repo"].get_by_id(before_new.user_id)
        == before_new
    )


@pytest.mark.asyncio
async def test_actual_committed_native_remap_invalidates_original_challenge(
    link_env,
):
    env = link_env
    view, _, _ = await proposed(env)
    target = await create_test_user(
        env["repos"]["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    # A separate ordinary SQL writer may change a mapping; legacy Instagram
    # attachment no longer does so. Current native authority must still fail.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            UserModel.__table__.update()
            .where(UserModel.user_id == env["user"].user_id)
            .values(max_id=None, max_chat_id=None)
        )
        db.execute(
            UserModel.__table__.update()
            .where(UserModel.user_id == target.user_id)
            .values(max_id=env["actor"].external_id)
        )
    before_old = await env["repos"]["user_repo"].get_by_id(env["user"].user_id)
    before_new = await env["repos"]["user_repo"].get_by_id(target.user_id)
    with pytest.raises(PermissionError, match="messenger_identity_changed"):
        await env["service"].status(env["actor"])
    with pytest.raises(PermissionError):
        await env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        )
    assert (
        await env["repos"]["user_repo"].get_by_id(before_old.user_id)
        == before_old
    )
    assert (
        await env["repos"]["user_repo"].get_by_id(before_new.user_id)
        == before_new
    )


@pytest.mark.parametrize(
    "table",
    [
        "messenger_link_challenges",
        "messenger_link_claims",
        "messenger_link_commands",
        "messenger_link_native_attempts",
        "messenger_link_native_results",
        "messenger_link_events",
    ],
)
@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE {table} SET {column}={column} WHERE false",
        "DELETE FROM {table} WHERE false",
        "TRUNCATE {table} CASCADE",
    ],
)
def test_fact_guards_reject_even_zero_row_mutation(
    financial_pg_engine, table, mutation
):
    columns = inspect(financial_pg_engine).get_columns(table)
    with financial_pg_engine.connect() as conn:
        with pytest.raises(
            Exception, match="messenger_link_evidence_immutable"
        ):
            conn.execute(
                text(mutation.format(table=table, column=columns[0]["name"]))
            )
        conn.rollback()


@pytest.mark.parametrize("operation", ["status", "confirm", "native", "revoke"])
@pytest.mark.asyncio
async def test_mutable_projection_cannot_borrow_other_challenge_claim(
    link_env, operation
):
    from ugc_bot.infrastructure.db.messenger_linking_models import STATE

    env = link_env
    view, native_a, _ = await proposed(env)
    other = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        messenger_type=MessengerType.MAX,
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], other.user_id
    )
    other_actor = MaxLinkActor(other.user_id, other.max_id)
    other_waiting = await env["service"].create(other_actor, "other-issue")
    other_claim = await env["service"].propose_native(proposal(other_waiting))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            STATE.update()
            .where(STATE.c.challenge_id == view.challenge_id)
            .values(claim_id=other_claim.claim_id)
        )
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        if operation == "status":
            await env["service"].status(env["actor"])
        elif operation == "confirm":
            await env["service"].confirm(
                env["actor"],
                view.challenge_id,
                other_claim.claim_id,
                view.version,
                "confirm",
            )
        elif operation == "native":
            await env["service"].propose_native(
                replace(native_a, update_id=str(uuid4().int % 10**12 + 1))
            )
        else:
            await env["service"].revoke(
                env["actor"], view.challenge_id, view.version, "revoke"
            )
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


@pytest.mark.parametrize("operation", ["status", "confirm", "native", "revoke"])
@pytest.mark.asyncio
async def test_old_projection_cannot_revive_immutable_revocation(
    link_env, operation
):
    from ugc_bot.infrastructure.db.messenger_linking_models import STATE

    env = link_env
    view, original, _ = await proposed(env)
    await env["service"].revoke(
        env["actor"], view.challenge_id, view.version, "revoke"
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            STATE.update()
            .where(STATE.c.challenge_id == view.challenge_id)
            .values(
                state="proposed", version=view.version, claim_id=view.claim_id
            )
        )
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        if operation == "status":
            await env["service"].status(env["actor"])
        elif operation == "confirm":
            await env["service"].confirm(
                env["actor"],
                view.challenge_id,
                view.claim_id,
                view.version,
                "confirm",
            )
        elif operation == "native":
            await env["service"].propose_native(
                replace(original, update_id=str(uuid4().int % 10**12 + 1))
            )
        else:
            await env["service"].revoke(
                env["actor"], view.challenge_id, view.version, "revoke-again"
            )
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


def test_metadata_created_facts_install_all_statement_guards(
    financial_pg_engine,
):
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import UUID

    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.messenger_linking_models import TABLES
    from ugc_bot.infrastructure.db.messenger_linking_schema import FACT_KEYS

    schema = "link_metadata_" + uuid4().hex
    with financial_pg_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}",public'))
        users = sa.Table(
            "users", sa.MetaData(), sa.Column("user_id", UUID, primary_key=True)
        )
        conn.execute(sa.schema.CreateTable(users))
        Base.metadata.create_all(conn, tables=list(TABLES.values()))
        try:
            for key in FACT_KEYS:
                table = TABLES[key]
                first = next(iter(table.c)).name
                for statement in [
                    f"UPDATE {table.name} SET {first}={first} WHERE false",
                    f"DELETE FROM {table.name} WHERE false",
                    f"TRUNCATE {table.name} CASCADE",
                ]:
                    with (
                        pytest.raises(
                            Exception, match="messenger_link_evidence_immutable"
                        ),
                        conn.begin_nested(),
                    ):
                        conn.exec_driver_sql(statement)
        finally:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


@pytest.mark.asyncio
async def test_sql_operation_fences_current_pair_and_terminal_replay(link_env):
    env = link_env
    with pytest.raises(ValueError, match="invalid_operation_key"):
        await env["service"].create(env["actor"], "")
    with pytest.raises(LookupError):
        await env["service"].status(env["actor"], uuid4())
    view, native, _ = await proposed(env)
    linked = await env["service"].confirm(
        env["actor"], view.challenge_id, view.claim_id, view.version, "confirm"
    )
    assert (
        await env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        )
    ).receipt == linked.receipt
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await env["service"].confirm(
            env["actor"], view.challenge_id, uuid4(), view.version, "confirm"
        )
    assert (
        await env["service"].create(env["actor"], "already-linked")
    ).state == "linked"
    current_user = await env["repos"]["user_repo"].get_by_id(
        env["actor"].user_id
    )
    await env["repos"]["user_repo"].save(
        replace(current_user, telegram_id=str(uuid4().int % 10**12 + 1))
    )
    replay = await env["service"].confirm(
        env["actor"], view.challenge_id, view.claim_id, view.version, "confirm"
    )
    assert (
        replay.receipt.state == "linked" and replay.state == "identity_changed"
    )
    assert replay.launch_url is None


@pytest.mark.asyncio
async def test_sql_revoke_and_creation_quota_are_durable(link_env):
    env = link_env
    for number in range(5):
        view = await env["service"].create(env["actor"], f"issue-{number}")
        if number == 0:
            with pytest.raises(ValueError, match="link_version_conflict"):
                await env["service"].revoke(
                    env["actor"], view.challenge_id, 99, "stale"
                )
        revoked = await env["service"].revoke(
            env["actor"], view.challenge_id, view.version, f"revoke-{number}"
        )
        replay = await env["service"].revoke(
            env["actor"], view.challenge_id, view.version, f"revoke-{number}"
        )
        assert replay.receipt == revoked.receipt
        with pytest.raises(ValueError, match="link_not_revocable"):
            await env["service"].revoke(
                env["actor"],
                view.challenge_id,
                revoked.version,
                f"again-{number}",
            )
    assert (
        await env["service"].create(env["actor"], "sixth")
    ).state == "rate_limited"


@pytest.mark.asyncio
async def test_sql_native_invalid_replay_conflict_and_quota(link_env):
    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    original = proposal(waiting)
    first = None
    for number in range(20):
        value = replace(
            original,
            update_id=str(int(original.update_id) + number),
            token="lk1_!",
        )
        receipt = await env["service"].propose_native(value)
        assert receipt.state == "invalid"
        if number == 0:
            first = value, receipt
    assert await env["service"].propose_native(first[0]) == first[1]
    assert (
        await env["service"].propose_native(
            replace(first[0], display_name="changed")
        )
    ).state == "conflict"
    limited = await env["service"].propose_native(
        replace(original, update_id=str(int(original.update_id) + 20))
    )
    assert limited.state == "rate_limited"


@pytest.mark.parametrize(
    "change", ["disabled", "unmapped", "same_kid_rotation"]
)
@pytest.mark.asyncio
async def test_sql_native_configuration_and_current_owner_fail_closed(
    link_env, change
):
    from pydantic import SecretStr

    from ugc_bot.infrastructure.messenger.link_tokens import LinkTokens

    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    original = proposal(waiting)
    if change == "disabled":
        env["service"].enabled = False
        assert (
            await env["service"].create(env["actor"], "disabled-new")
        ).state == "unavailable"
    elif change == "unmapped":
        before = await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
        await env["repos"]["user_repo"].save(replace(before, max_id=None))
    else:
        env["service"].tokens = LinkTokens(
            SecretStr(base64.urlsafe_b64encode(b"r" * 32).decode().rstrip("=")),
            env["service"].scope,
        )
    assert (
        await env["service"].propose_native(original)
    ).state == "unavailable"
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_sql_foreign_active_reservation_and_expiry_are_authoritative(
    link_env,
):
    env = link_env
    first, original, _ = await proposed(env)
    other = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        messenger_type=MessengerType.MAX,
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], other.user_id
    )
    actor = MaxLinkActor(other.user_id, other.max_id)
    env["clock"].value += timedelta(seconds=599)
    waiting = await env["service"].create(actor, "issue-other")
    second = proposal(waiting, sender=original.sender_id)
    assert (await env["service"].propose_native(second)).state == "conflict"
    env["clock"].value += timedelta(seconds=2)
    result = await env["service"].propose_native(
        replace(second, update_id=str(uuid4().int % 10**12 + 1))
    )
    assert result.state == "proposed"
    assert (await env["service"].status(env["actor"])).state == "expired"


@pytest.mark.asyncio
async def test_sql_duplicate_native_workers_share_one_immutable_claim(link_env):
    import asyncio

    from ugc_bot.infrastructure.db.messenger_linking_models import CLAIMS

    env = link_env
    waiting = await env["service"].create(env["actor"], "issue")
    value = proposal(waiting)
    results = await asyncio.gather(
        *(env["service"].propose_native(value) for _ in range(5))
    )
    assert all(result == results[0] for result in results)
    with Session(env["pg"]) as db:
        assert (
            len(
                db.scalars(
                    select(CLAIMS.c.claim_id).where(
                        CLAIMS.c.challenge_id == waiting.challenge_id
                    )
                ).all()
            )
            == 1
        )


@pytest.mark.parametrize("projection", ["owner", "telegram"])
@pytest.mark.parametrize(
    "operation", ["status", "create", "native", "confirm", "revoke"]
)
@pytest.mark.asyncio
async def test_sql_live_facts_require_active_projection(
    link_env, projection, operation
):
    from ugc_bot.infrastructure.db.messenger_linking_models import (
        ACTIVE_OWNER,
        ACTIVE_TG,
    )

    env = link_env
    view, proof, _ = await proposed(env)
    table = ACTIVE_OWNER if projection == "owner" else ACTIVE_TG
    condition = (
        table.c.owner_id == env["actor"].user_id
        if projection == "owner"
        else table.c.telegram_id == proof.sender_id
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(table.delete().where(condition))
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        if operation == "status":
            await env["service"].status(env["actor"])
        elif operation == "create":
            await env["service"].create(env["actor"], "new")
        elif operation == "native":
            await env["service"].propose_native(
                replace(proof, update_id=str(uuid4()))
            )
        elif operation == "confirm":
            await env["service"].confirm(
                env["actor"],
                view.challenge_id,
                view.claim_id,
                view.version,
                "confirm",
            )
        else:
            await env["service"].revoke(
                env["actor"], view.challenge_id, view.version, "revoke"
            )
    assert (
        await env["repos"]["user_repo"].get_by_id(env["actor"].user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_sql_missing_tg_projection_cannot_duplicate_foreign_live_claim(
    link_env,
):
    from ugc_bot.domain.messenger_linking import MaxLinkActor
    from ugc_bot.infrastructure.db.messenger_linking_models import ACTIVE_TG

    env = link_env
    _, proof, _ = await proposed(env)
    other = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4()),
        messenger_type=MessengerType.MAX,
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], other.user_id
    )
    second = await env["service"].create(
        MaxLinkActor(other.user_id, other.max_id), "other"
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            ACTIVE_TG.delete().where(ACTIVE_TG.c.telegram_id == proof.sender_id)
        )
    with pytest.raises(ValueError, match="messenger_state_unavailable"):
        await env["service"].propose_native(
            proposal(second, sender=proof.sender_id)
        )
    assert (
        await env["repos"]["user_repo"].get_by_id(other.user_id)
    ).telegram_id is None


@pytest.mark.asyncio
async def test_sql_waiting_history_and_stale_owner_pointer_fail_closed(
    link_env,
):
    from ugc_bot.infrastructure.db.messenger_linking_models import (
        ACTIVE_OWNER,
        CHALLENGES,
    )

    env = link_env
    old = await env["service"].create(env["actor"], "old")
    env["clock"].value += timedelta(seconds=601)
    current = await env["service"].create(env["actor"], "current")
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            ACTIVE_OWNER.update()
            .where(ACTIVE_OWNER.c.owner_id == env["actor"].user_id)
            .values(challenge_id=old.challenge_id)
        )
    for action in [
        lambda: env["service"].status(env["actor"]),
        lambda: env["service"].create(env["actor"], "second-live"),
        lambda: env["service"].propose_native(proposal(current)),
    ]:
        with pytest.raises(ValueError, match="messenger_state_unavailable"):
            await action()
    with Session(env["pg"]) as db:
        assert (
            len(
                db.scalars(
                    select(CHALLENGES.c.challenge_id).where(
                        CHALLENGES.c.owner_id == env["actor"].user_id
                    )
                ).all()
            )
            == 2
        )


@pytest.mark.parametrize("terminal", ["expired", "revoked", "linked"])
@pytest.mark.asyncio
async def test_sql_obsolete_projections_are_not_mandatory_forever(
    link_env, terminal
):
    from ugc_bot.infrastructure.db.messenger_linking_models import (
        ACTIVE_OWNER,
        ACTIVE_TG,
    )

    env = link_env
    view, proof, _ = await proposed(env)
    if terminal == "expired":
        env["clock"].value += timedelta(seconds=601)
    elif terminal == "revoked":
        await env["service"].revoke(
            env["actor"], view.challenge_id, view.version, "revoke"
        )
    else:
        await env["service"].confirm(
            env["actor"],
            view.challenge_id,
            view.claim_id,
            view.version,
            "confirm",
        )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            ACTIVE_OWNER.delete().where(
                ACTIVE_OWNER.c.owner_id == env["actor"].user_id
            )
        )
        db.execute(
            ACTIVE_TG.delete().where(ACTIVE_TG.c.telegram_id == proof.sender_id)
        )
    result = await env["service"].create(env["actor"], "after-terminal")
    assert result.state == ("linked" if terminal == "linked" else "waiting")
    if terminal != "linked":
        assert result.challenge_id != view.challenge_id
        assert (
            await env["service"].propose_native(
                proposal(result, sender=proof.sender_id)
            )
        ).state == "proposed"
