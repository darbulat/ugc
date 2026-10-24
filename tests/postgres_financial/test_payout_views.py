"""Read-only payout facts against real paid work and migrated PostgreSQL."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)
from tests.postgres_financial.test_payout_runtime import (
    prepare,
    request_command,
    result_command,
    review_command,
)
from ugc_bot.application.payout_view_ports import Page, PayoutReadPrincipal
from ugc_bot.config import MaxBotConfig
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.payout_models import TABLE_MAP
from ugc_bot.miniapp.api import router

__all__ = ["capture_env", "payout_env"]
PATH = "/miniapp/api/payouts/read"


def runtime(env, platform="telegram"):
    identifiers = {
        u: str(uuid4().int % 10**14 + 1)
        for u in (env["client"], env["flow"]["manager"])
    }
    env["config"].max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-max-token")
    with Session(env["pg"]) as db, db.begin():
        for user, native in identifiers.items():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == user)
                .values(telegram_id=native, max_id=native, country=None)
            )
    dispatcher = env["flow"]["container"].build_bot_services()
    service = dispatcher["payout_view_service"]
    assert service is not None
    service.clock = env["service"].clock
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config, app.state.dispatcher = env["config"], dispatcher
    token = (
        env["config"].bot.bot_token
        if platform == "telegram"
        else env["config"].max_bot.token
    )

    def auth(user):
        return dict(
            init_data=generate_init_data(
                token, int(identifiers[user]), "Synthetic reader"
            ),
            platform=platform,
        )

    def principal(user):
        return PayoutReadPrincipal(user, platform, identifiers[user])

    return service, app, auth, principal


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_paid_source_container_signed_context_and_preview(
    payout_env, platform
):
    env = payout_env
    service, app, auth, principal = runtime(env, platform)
    owner = env["flow"]["manager"]
    with Session(env["pg"]) as db:
        before = len(db.execute(select(UserModel.user_id)).all())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(PATH + "/context", json=auth(owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["financial"]["state"] == "ready"
        assert body["financial"]["balances"]["available_minor"] == "60000"
        assert (
            body["requirements"]["document"] == env["requirements"]["document"]
        )
        assert body["masked_requisites"]["entries"][0]["usable"]
        preview = await client.post(
            PATH + "/reserve-preview",
            json=auth(owner)
            | dict(
                requisites_id=env["requisites"]["requisites_id"],
                amount_minor="60000",
            ),
        )
        assert preview.status_code == 200 and preview.json()["can_reserve"]
        assert preview.json()["amount_minor"] == "60000"
        assert all(
            v not in response.text + preview.text
            for v in env["details"].values()
        )
        assert response.headers["cache-control"] == "no-store"
    with Session(env["pg"]) as db:
        assert len(db.execute(select(UserModel.user_id)).all()) == before
        assert db.get(UserModel, owner).country is None
        assert not db.scalar(
            select(TABLE_MAP["requests"].c.request_id).where(
                TABLE_MAP["requests"].c.recipient_id == owner
            )
        )
    async with service.repository.snapshot() as snapshot:
        actor = await snapshot.actor(principal(owner))
        assert actor.actor_id == owner
        assert (
            await snapshot.session.scalar(
                text("SELECT current_setting('transaction_isolation')")
            )
            == "repeatable read"
        )
        assert (
            await snapshot.session.scalar(
                text("SELECT current_setting('transaction_read_only')")
            )
            == "on"
        )
    with pytest.raises(DBAPIError, match="read-only"):
        async with service.repository.snapshot() as snapshot:
            await snapshot.session.execute(
                update(UserModel)
                .where(UserModel.user_id == owner)
                .values(username="forbidden read write")
            )


@pytest.mark.asyncio
async def test_rr_does_not_mix_projection_change_and_next_response_sees_it(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    owner = env["flow"]["manager"]
    wallet = Base.metadata.tables["financial_wallets"]
    try:
        async with service.repository.snapshot() as snapshot:
            await snapshot.actor(principal(owner))
            before = await snapshot.financial(owner)
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(wallet)
                    .where(
                        wallet.c.recipient_id == owner,
                        wallet.c.currency == "RUB",
                    )
                    .values(available_minor=59999)
                )
            after = await snapshot.financial(owner)
            assert (
                before.wallet == after.wallet
                and before.wallet["available"] == 60000
            )
        fresh = await service.context(principal(owner))
        assert (
            fresh["financial"]["state"] == "unavailable"
            and fresh["financial"]["balances"] is None
        )
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(wallet)
                .where(
                    wallet.c.recipient_id == owner, wallet.c.currency == "RUB"
                )
                .values(available_minor=60000)
            )


@pytest.mark.asyncio
async def test_missing_protocol_column_blocks_money_without_aborting_read(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    with env["pg"].begin() as db:
        db.execute(
            text(
                "ALTER TABLE payout_requests RENAME COLUMN payout_protocol "
                "TO synthetic_hidden_protocol"
            )
        )
    try:
        response = await service.context(principal(env["flow"]["manager"]))
        assert response["financial"]["balances"]["available_minor"] == "60000"
        assert not response["capabilities"]["begin_request"]
        assert "payout_source_unavailable" in response["recipient_blockers"]
    finally:
        with env["pg"].begin() as db:
            db.execute(
                text(
                    "ALTER TABLE payout_requests RENAME COLUMN "
                    "synthetic_hidden_protocol TO payout_protocol"
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_mapping_change_between_resolution_and_snapshot_denies(
    payout_env, monkeypatch, platform
):
    from ugc_bot.miniapp import payout_view_api

    env = payout_env
    _, app, auth, _ = runtime(env, platform)
    owner = env["flow"]["manager"]
    real = payout_view_api.resolve_payout_read_principal

    async def raced(*args, **kwargs):
        principal = await real(*args, **kwargs)
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == owner)
                .values(
                    **{
                        "telegram_id"
                        if platform == "telegram"
                        else "max_id": "synthetic-remapped-" + str(uuid4())
                    }
                )
            )
        return principal

    monkeypatch.setattr(payout_view_api, "resolve_payout_read_principal", raced)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(PATH + "/context", json=auth(owner))
    assert response.status_code == 403 and "60000" not in response.text


@pytest.mark.asyncio
async def test_over100_equal_time_queue_keeps_false_terminal_and_missing_state(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    states = []
    for i in range(110):
        states.append(
            await env["execute"](
                request_command(
                    env, operation_key=f"9gb-many:{i}", amount_minor=1
                )
            )
        )
    first = states[0]
    approved = await env["execute"](review_command(env, first, "review"))
    prepared = await env["execute"](review_command(env, approved, "start"))
    paid = await env["execute"](result_command(env, prepared, amount_minor=1))
    assert paid["state"] == "paid"
    blocked = await env["execute"](review_command(env, states[3], "review"))
    blocked = await env["execute"](review_command(env, blocked, "start"))
    retained = blocked
    blocked = await env["execute"](result_command(env, blocked, amount_minor=1))
    blocked = await env["execute"](
        result_command(
            env, retained, expected_version=blocked["version"], status="unknown"
        )
    )
    assert blocked["state"] == "paid" and blocked["block_reason"]
    target = TABLE_MAP["states"]

    false_terminal, missing = (UUID(states[i]["request_id"]) for i in (1, 2))
    cleared_blocker = UUID(blocked["request_id"])
    with Session(env["pg"]) as db, db.begin():
        originals = tuple(
            dict(r)
            for r in db.execute(
                select(target).where(
                    target.c.request_id.in_(
                        (false_terminal, missing, cleared_blocker)
                    )
                )
            ).mappings()
        )
        db.execute(
            update(target)
            .where(target.c.request_id == false_terminal)
            .values(state="paid", block_reason="")
        )
        db.execute(delete(target).where(target.c.request_id == missing))
        db.execute(
            update(target)
            .where(target.c.request_id == cleared_blocker)
            .values(block_reason="")
        )
    try:
        ids = []
        cursor = None
        found = {}
        for _ in range(100):
            page = await service.queue_page(
                principal(env["client"]), page=Page(limit=17, cursor=cursor)
            )
            for row in page["entries"]:
                assert row["request_id"] not in ids
                ids.append(row["request_id"])
                found[row["request_id"]] = row
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        else:
            pytest.fail("queue did not reach a bounded end")
        assert first["request_id"] not in found
        assert {row["request_id"] for row in states[1:]} <= set(ids)
        for bad in (false_terminal, missing, cleared_blocker):
            row = found[str(bad)]
            assert row["state"] == "unavailable" and row["version"] is None
            assert not set(row["allowed_actions"]) & {
                "review",
                "reject",
                "start",
                "escalate",
            }
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                delete(target).where(
                    target.c.request_id.in_(
                        (false_terminal, missing, cleared_blocker)
                    )
                )
            )
            db.execute(insert(target), originals)

        own_ids, cursor = [], None
        while True:
            own = await service.own_page(
                principal(env["flow"]["manager"]),
                page=Page(limit=19, cursor=cursor),
            )
            own_ids += [r["request_id"] for r in own["entries"]]
            if not own["has_more"]:
                break
            cursor = own["next_cursor"]
        assert len(own_ids) == len(set(own_ids)) == 110
        assert set(own_ids) == {r["request_id"] for r in states}


@contextmanager
def hidden_source(env, table, column=None):
    """Reversible physical old-schema simulation in the private test schema."""
    before = (
        f'ALTER TABLE "{table}" RENAME COLUMN "{column}" TO synthetic_hidden'
        if column
        else f'ALTER TABLE "{table}" RENAME TO synthetic_hidden'
    )
    after = (
        f'ALTER TABLE "{table}" RENAME COLUMN synthetic_hidden TO "{column}"'
        if column
        else f'ALTER TABLE synthetic_hidden RENAME TO "{table}"'
    )
    with env["pg"].begin() as db:
        db.execute(text(before))
    try:
        yield
    finally:
        with env["pg"].begin() as db:
            db.execute(text(after))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,column,display",
    [
        ("financial_payout_commands", None, "ready"),
        ("financial_payout_commands", "result", "ready"),
        ("financial_obligations", "snapshot_id", "ready"),
        ("financial_movements", "amount_minor", "unavailable"),
        ("financial_wallets", None, "unavailable"),
        ("financial_payout_allocations", None, "ready"),
        ("financial_payout_settlements", "outcome_id", "ready"),
        ("legacy_financial_guards", None, "ready"),
    ],
)
async def test_actual_missing_physical_source_never_advertises_reserve(
    payout_env, table, column, display
):
    env = payout_env
    service, app, auth, principal = runtime(env)
    owner = env["flow"]["manager"]
    state = await env["execute"](request_command(env, amount_minor=1))
    approved = await env["execute"](review_command(env, state, "review"))
    with hidden_source(env, table, column):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(PATH + "/context", json=auth(owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["financial"]["state"] == display
        assert not body["capabilities"]["begin_request"]
        assert "payout_source_unavailable" in body["recipient_blockers"]
        if display == "ready":
            assert body["financial"]["balances"]["available_minor"] == "59999"
        else:
            assert body["financial"]["balances"] is None
        preview = await service.reserve_preview(
            principal(owner), UUID(env["requisites"]["requisites_id"]), 1
        )
        assert not preview["can_reserve"]
        detail = await service.detail(
            principal(env["client"]), UUID(approved["request_id"])
        )
        assert not {"review", "reject", "start"} & set(
            detail["allowed_actions"]
        )
        async with service.repository.snapshot() as snapshot:
            await snapshot.financial(owner)
            assert await snapshot.session.scalar(text("SELECT 42")) == 42


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column", ["country", "max_chat_id", "username", "referral_payout_rate"]
)
async def test_actual_retained_observation_preflights_full_writer_user(
    payout_env, column
):
    env = payout_env
    prepared = await prepare(env)
    service, _, _, principal = runtime(env)
    service.crypto = None
    env["config"].financial.payouts_enabled = False
    with hidden_source(env, "users", column):
        detail = await service.detail(
            principal(env["client"]), UUID(prepared["request_id"])
        )
        assert detail["observation"]["retained_intents"]["entries"]
        assert "record_observation" not in detail["allowed_actions"]
        assert detail["action_blockers"]["record_observation"] == [
            "payout_observation_source_unavailable"
        ]
        assert not detail["allowed_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_unknown_and_changed_roles_never_reuse_authority(
    payout_env, platform
):
    env = payout_env
    _, app, auth, _ = runtime(env, platform)
    owner, admin = env["flow"]["manager"], env["client"]
    await env["execute"](request_command(env, amount_minor=1))
    await env["execute"](
        request_command(env, operation_key="read-role-second", amount_minor=1)
    )
    token = (
        env["config"].bot.bot_token
        if platform == "telegram"
        else env["config"].max_bot.token
    )
    with Session(env["pg"]) as db:
        before = db.scalar(select(text("count(*)")).select_from(UserModel))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        unknown = await client.post(
            PATH + "/context",
            json=dict(
                platform=platform,
                init_data=generate_init_data(
                    token, uuid4().int % 10**14 + 1, "Unknown synthetic"
                ),
            ),
        )
        assert unknown.status_code == 404
        first = await client.post(
            PATH + "/admin/queue", json=auth(admin) | {"limit": 1}
        )
        assert first.status_code == 200 and first.json()["has_more"]
        cursor = first.json()["next_cursor"]
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == admin)
                .values(admin=False)
            )
        denied = await client.post(
            PATH + "/admin/queue",
            json=auth(admin) | {"limit": 1, "cursor": cursor},
        )
        assert denied.status_code == 403 and "fence" not in denied.text
        foreign = await client.post(
            PATH + "/own", json=auth(owner) | {"cursor": cursor}
        )
        assert foreign.status_code == 422
        for status in ("pause", "bot_blocked"):
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == owner)
                    .values(status=status)
                )
            own = await client.post(PATH + "/context", json=auth(owner))
            assert (
                own.status_code == 200
                and own.json()["capabilities"]["read_own_requests"]
            )
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == owner)
                .values(status="blocked")
            )
        denied = await client.post(PATH + "/context", json=auth(owner))
        assert denied.status_code == 403
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(text("count(*)")).select_from(UserModel)) == before
        )
        assert db.get(UserModel, owner).country is None


@pytest.mark.asyncio
async def test_actual_empty_and_missing_wallet_never_create_projection(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    wallet = Base.metadata.tables["financial_wallets"]
    empty = await service.context(principal(env["client"]))
    assert empty["financial"]["state"] == "known_empty"
    assert empty["financial"]["balances"]["available_minor"] == "0"
    with Session(env["pg"]) as db, db.begin():
        assert (
            db.scalar(
                select(wallet.c.recipient_id).where(
                    wallet.c.recipient_id == env["client"]
                )
            )
            is None
        )
        original = dict(
            db.execute(
                select(wallet).where(
                    wallet.c.recipient_id == env["flow"]["manager"]
                )
            )
            .mappings()
            .one()
        )
        db.execute(
            delete(wallet).where(
                wallet.c.recipient_id == env["flow"]["manager"]
            )
        )
    try:
        missing = await service.context(principal(env["flow"]["manager"]))
        assert missing["financial"]["state"] == "unavailable"
        assert missing["financial"]["balances"] is None
        assert "payout_wallet_missing" in missing["recipient_blockers"]
        with Session(env["pg"]) as db:
            assert (
                db.scalar(
                    select(wallet.c.recipient_id).where(
                        wallet.c.recipient_id == env["flow"]["manager"]
                    )
                )
                is None
            )
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(insert(wallet).values(original))


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["reserved", "paid"])
async def test_actual_balanced_unproven_p01_history_stays_display_only(
    payout_env, target
):
    from tests.postgres_financial.test_payout_history_readiness import (
        foundation_history,
    )

    env = payout_env
    await foundation_history(env, target)
    service, _, _, principal = runtime(env)
    response = await service.context(principal(env["flow"]["manager"]))
    assert response["financial"]["state"] == "ready"
    assert response["financial"]["balances"]["available_minor"] == "30000"
    assert (
        "payout_history_authority_review_required"
        in response["recipient_blockers"]
    )
    assert not response["capabilities"]["begin_request"]


@pytest.mark.asyncio
async def test_actual_actions_follow_fresh_events_and_retained_execution(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    admin, owner = principal(env["client"]), principal(env["flow"]["manager"])
    reserved = await env["execute"](request_command(env, amount_minor=100))
    request_id = UUID(reserved["request_id"])
    detail = await service.detail(admin, request_id)
    assert {"review", "reject"} <= set(detail["allowed_actions"])
    assert "start" not in detail["allowed_actions"]
    approved = await env["execute"](review_command(env, reserved, "review"))
    detail = await service.detail(admin, request_id)
    assert {"review", "reject", "start"} <= set(detail["allowed_actions"])
    service.config.manual_bank_account_id = ""
    detail = await service.detail(admin, request_id)
    assert (
        "start" not in detail["allowed_actions"]
        and "review" in detail["allowed_actions"]
    )
    service.config.manual_bank_account_id = "synthetic-origin-account"
    prepared = await env["execute"](review_command(env, approved, "start"))
    detail = await service.detail(admin, request_id)
    assert (
        detail["current_execution"]["execution_id"] == prepared["execution_id"]
    )
    assert (
        detail["current_execution"]["expected_version"] == prepared["version"]
    )
    assert "record_observation" in detail["allowed_actions"]
    assert not {"review", "reject", "start"} & set(detail["allowed_actions"])
    safe = await service.detail(owner, request_id)
    assert "current_execution" not in safe and "observation" not in safe
    assert "fence" not in str(safe) and "evidence_reference" not in str(safe)
    env["config"].financial.payouts_enabled = False
    service.crypto = None
    paused = await service.detail(admin, request_id)
    assert paused["allowed_actions"] == ["record_observation"]
    observation = await env["execute"](
        result_command(env, prepared, amount_minor=101)
    )
    assert observation["state"] == "unknown"
    context = await service.context(owner)
    assert (
        "payout_bank_reconciliation_required" in context["recipient_blockers"]
    )
    detail = await service.detail(admin, request_id)
    assert detail["version"] == observation["version"]
    assert (
        detail["current_execution"]["expected_version"]
        == observation["version"]
    )
    with Session(env["pg"]) as db, db.begin():
        original = dict(
            db.execute(
                select(TABLE_MAP["states"]).where(
                    TABLE_MAP["states"].c.request_id == request_id
                )
            )
            .mappings()
            .one()
        )
        db.execute(
            update(TABLE_MAP["states"])
            .where(TABLE_MAP["states"].c.request_id == request_id)
            .values(state="paid")
        )
    try:
        broken = await service.detail(admin, request_id)
        assert (
            broken["state"] == "unavailable"
            and broken["current_execution"] is None
        )
        retained = broken["observation"]["retained_intents"]["entries"][0]
        assert retained["version_provenance"] == "retained_event"
        assert retained["expected_version"] == observation["version"]
        assert broken["allowed_actions"] == ["record_observation"]
    finally:
        # Restore only the explicitly corrupted mutable fixture projection.
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(TABLE_MAP["states"])
                .where(TABLE_MAP["states"].c.request_id == request_id)
                .values(**original)
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "financial_payout_terms_documents",
        "financial_payout_requirement_contracts",
        "financial_payout_requisites_acceptances",
    ],
)
async def test_actual_missing_readable_companion_does_not_erase_history(
    payout_env, table
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    with hidden_source(env, table):
        response = await service.context(principal(env["flow"]["manager"]))
        assert response["financial"]["balances"]["available_minor"] == "59999"
        assert not response["requirements"]["readable"]
        assert response["requirements"]["document"] is None
        assert not response["capabilities"]["begin_request"]
        assert not response["masked_requisites"]["entries"][0]["usable"]
        detail = await service.detail(
            principal(env["client"]), UUID(state["request_id"])
        )
        assert {"review", "reject", "start"} <= set(detail["allowed_actions"])


@contextmanager
def damaged_movement(env, kind):
    table = Base.metadata.tables["financial_movements"]
    obligation = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db, db.begin():
        row = dict(
            db.execute(
                select(table)
                .join(obligation, obligation.c.id == table.c.obligation_id)
                .where(
                    obligation.c.recipient_id == env["flow"]["manager"],
                    table.c.movement_type == "issuance",
                )
            )
            .mappings()
            .one()
        )
        db.execute(text("ALTER TABLE financial_movements DISABLE TRIGGER ALL"))
        if kind == "missing_issuance":
            db.execute(delete(table).where(table.c.id == row["id"]))
        else:
            db.execute(
                update(table)
                .where(table.c.id == row["id"])
                .values(
                    obligation_id=uuid4()
                    if kind == "orphan"
                    else row["obligation_id"],
                    amount_minor=row["amount_minor"]
                    + (1 if kind == "wrong_issuance" else 0),
                )
            )
        db.execute(text("ALTER TABLE financial_movements ENABLE TRIGGER ALL"))
    try:
        yield
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                text("ALTER TABLE financial_movements DISABLE TRIGGER ALL")
            )
            if kind == "missing_issuance":
                columns = ", ".join(f'"{name}"' for name in row)
                values = ", ".join(f":{name}" for name in row)
                db.execute(
                    text(
                        f"INSERT INTO financial_movements ({columns}) "
                        f"OVERRIDING SYSTEM VALUE VALUES ({values})"
                    ),
                    row,
                )
            else:
                db.execute(
                    update(table)
                    .where(table.c.id == row["id"])
                    .values(
                        obligation_id=row["obligation_id"],
                        amount_minor=row["amount_minor"],
                    )
                )
            db.execute(
                text("ALTER TABLE financial_movements ENABLE TRIGGER ALL")
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["orphan", "missing_issuance", "wrong_issuance"]
)
async def test_damaged_raw_journal_is_unavailable_and_never_repaired(
    payout_env, kind
):
    env = payout_env
    service, _, _, principal = runtime(env)
    with damaged_movement(env, kind):
        response = await service.context(principal(env["flow"]["manager"]))
        assert response["financial"]["state"] == "unavailable"
        assert response["financial"]["balances"] is None
        assert not response["capabilities"]["begin_request"]
        if kind == "orphan":
            empty = await service.context(principal(env["client"]))
            assert empty["financial"]["state"] == "unavailable"
            assert (
                "payout_source_integrity_required"
                in empty["recipient_blockers"]
            )
            assert "60000" not in str(empty)


@pytest.mark.asyncio
async def test_actual_masked_and_publication_keysets_and_future_document(
    payout_env,
):
    env = payout_env
    service, app, auth, principal = runtime(env)
    owner, admin = principal(env["flow"]["manager"]), principal(env["client"])
    requisites = {env["requisites"]["requisites_id"]}
    for i in range(104):
        row = await env["execute"](
            replace(env["store"], operation_key=f"9gb-mask:{i}")
        )
        requisites.add(row["requisites_id"])
    first = await service.context(owner, page=Page(limit=100))
    assert len(first["masked_requisites"]["entries"]) == 100
    assert first["masked_requisites"]["has_more"]
    next_page = await service.masked_page(
        owner,
        page=Page(limit=100, cursor=first["masked_requisites"]["next_cursor"]),
    )
    ids = [
        r["requisites_id"]
        for r in first["masked_requisites"]["entries"] + next_page["entries"]
    ]
    assert len(ids) == len(set(ids)) == 105 and set(ids) == requisites
    assert not next_page["has_more"]
    current_id = env["requirements"]["requirements_id"]
    latest = env["requirements"]
    for i in range(4):
        latest = await env["execute"](
            replace(
                env["publication"],
                operation_key=f"9gb-future:{i}",
                expected_version=latest["version"],
                effective_from=env["flow"]["clock"].at + timedelta(days=i + 1),
            )
        )
    context = await service.context(admin)
    assert context["requirements"]["requirements_id"] == current_id
    assert (
        context["latest_publication"]["requirements_id"]
        == latest["requirements_id"]
    )
    async with service.repository.snapshot() as snapshot:
        before_publication = await snapshot.requirements(
            env["now"] - timedelta(days=1)
        )
        assert before_publication.current is None
        assert (
            str(before_publication.latest["requirements_id"])
            == latest["requirements_id"]
        )
    cursor, published = None, []
    while True:
        page = await service.requirements_page(
            admin, page=Page(limit=2, cursor=cursor)
        )
        published += [r["requirements_id"] for r in page["entries"]]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(published) == len(set(published))
    assert {current_id, latest["requirements_id"]} <= set(published)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        bad = await client.post(
            PATH + "/masked",
            json=auth(env["client"])
            | {"cursor": first["masked_requisites"]["next_cursor"]},
        )
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_actual_protected_histories_keep_independent_scoped_keysets(
    payout_env,
):
    from ugc_bot.domain.financial import MAX_MINOR

    env = payout_env
    state = await prepare(env, amount=1)
    retained = state
    for amount in (MAX_MINOR, -MAX_MINOR, 0, None, 2**53 + 1):
        state = await env["execute"](
            result_command(
                env,
                retained,
                expected_version=state["version"],
                amount_minor=amount,
            )
        )
    service, _, _, principal = runtime(env)
    admin, owner = principal(env["client"]), principal(env["flow"]["manager"])
    request_id = UUID(state["request_id"])
    collections = {}
    for kind, identity in (
        ("events", "event_id"),
        ("intents", "execution_id"),
        ("outcomes", "outcome_id"),
        ("settlements", "execution_id"),
    ):
        cursor, values = None, []
        while True:
            page = await service.history_page(
                admin, request_id, kind, page=Page(limit=2, cursor=cursor)
            )
            values += page["entries"]
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        assert len(values) == len({v[identity] for v in values})
        collections[kind] = values
    assert {r["amount_minor"] for r in collections["outcomes"]} == {
        str(MAX_MINOR),
        str(-MAX_MINOR),
        "0",
        None,
        str(2**53 + 1),
    }
    assert all(not r["applied"] for r in collections["outcomes"])
    assert len(collections["intents"]) == 1 and not collections["settlements"]
    assert collections["intents"][0]["version_provenance"] == "retained_event"
    first = await service.history_page(
        admin, request_id, "events", page=Page(limit=1)
    )
    with pytest.raises(ValueError, match="payout_cursor_invalid"):
        await service.history_page(
            admin,
            request_id,
            "outcomes",
            page=Page(limit=1, cursor=first["next_cursor"]),
        )
    with pytest.raises(PermissionError):
        await service.history_page(owner, request_id, "events")


@pytest.mark.asyncio
async def test_actual_selected_item_dispute_blocks_only_its_exact_preview(
    payout_env,
):
    from ugc_bot.application.collaboration_ports import CollaborationCommand
    from ugc_bot.infrastructure.db.models import OrderItemModel
    from ugc_bot.infrastructure.db.repositories.item_assignments import (
        SqlAlchemyItemAssignmentRepository,
    )

    env = payout_env
    flow = env["flow"]
    service, _, _, principal = runtime(env)
    lifecycle = flow["container"].build_bot_services()["collaboration_service"]

    async def dispute(item, expected_version):
        async with flow["container"].transaction_manager.transaction() as db:
            assignment = await SqlAlchemyItemAssignmentRepository().replace(
                paid_item_id=item,
                expected_version=expected_version,
                creator_id=flow["creator"],
                manager_id=flow["manager"],
                actor_id=env["client"],
                reason="Synthetic replacement assigned for actual dispute",
                at=flow["clock"].at,
                session=db,
            )
        for version, action, actor, changes in (
            (
                0,
                "assign",
                env["client"],
                dict(
                    due_at=flow["clock"].at + timedelta(days=2),
                    terms_reference="synthetic:replacement-scope",
                ),
            ),
            (1, "start", env["client"], {}),
            (
                2,
                "claim",
                flow["creator"],
                {"evidence": "synthetic:actual-work-claim"},
            ),
            (
                3,
                "dispute",
                env["client"],
                {"reason": "Synthetic actual opposite-party dispute"},
            ),
        ):
            async with flow[
                "container"
            ].transaction_manager.transaction() as db:
                await lifecycle.execute(
                    CollaborationCommand(
                        assignment_id=assignment.assignment_id,
                        action=action,
                        operation_key="9gb-dispute:"
                        + str(assignment.assignment_id)
                        + ":"
                        + action,
                        actor_id=actor,
                        expected_version=version,
                        **changes,
                    ),
                    session=db,
                )

    with Session(env["pg"]) as db:
        unrelated = db.scalar(
            select(OrderItemModel.paid_item_id).where(
                OrderItemModel.order_id == env["order"],
                OrderItemModel.paid_item_id != flow["item"],
            )
        )
    await dispute(unrelated, 0)
    owner = principal(flow["manager"])
    requisite = UUID(env["requisites"]["requisites_id"])
    clear = await service.reserve_preview(owner, requisite, 50)
    assert clear["can_reserve"]
    async with service.repository.snapshot() as snapshot:
        assert await snapshot.item_blockers((unrelated,)) == ("work_disputed",)
        assert await snapshot.item_blockers((uuid4(),)) == (
            "payout_item_corrected_review_required",
        )
    await dispute(flow["item"], 1)
    blocked = await service.reserve_preview(owner, requisite, 50)
    assert not blocked["can_reserve"] and "work_disputed" in blocked["blockers"]
    assert str(unrelated) not in str(blocked) and str(flow["item"]) not in str(
        blocked
    )


@pytest.mark.asyncio
async def test_deadline_equality_escalates_once_and_receipt_stays_historical(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    original = state
    state = await env["execute"](review_command(env, state, "review"))
    admin, request_id = principal(env["client"]), UUID(state["request_id"])
    before = await service.detail(admin, request_id)
    assert not before["overdue"] and "escalate" not in before["allowed_actions"]
    env["flow"]["clock"].at += timedelta(hours=72)
    equality = await service.detail(admin, request_id)
    assert equality["overdue"] and "escalate" in equality["allowed_actions"]
    state = await env["execute"](review_command(env, state, "escalate"))
    after = await service.detail(admin, request_id)
    assert after["version"] == state["version"] > original["version"]
    assert "escalate" not in after["allowed_actions"]
    assert (
        await env["execute"](request_command(env, amount_minor=1))
    ) == original


@pytest.mark.asyncio
async def test_actual_new_terms_and_recipient_pause_preserve_release_action(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    await env["execute"](
        replace(
            env["publication"],
            operation_key="9gb-new-current",
            expected_version=env["requirements"]["version"],
        )
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["flow"]["manager"])
            .values(status="pause")
        )
    detail = await service.detail(
        principal(env["client"]), UUID(state["request_id"])
    )
    assert "payout_requirements_changed" in detail["action_blockers"]["review"]
    assert "start" not in detail["allowed_actions"]
    assert "reject" in detail["allowed_actions"]
    rejected = await env["execute"](review_command(env, state, "reject"))
    assert rejected["state"] == "rejected"
    after = await service.detail(
        principal(env["client"]), UUID(state["request_id"])
    )
    assert not {"review", "reject", "start", "escalate"} & set(
        after["allowed_actions"]
    )


@pytest.mark.asyncio
async def test_malformed_execution_event_never_fabricates_retained_version(
    payout_env,
):
    env = payout_env
    state = await prepare(env, amount=1)
    service, _, _, principal = runtime(env)
    table, request_id = TABLE_MAP["events"], UUID(state["request_id"])
    with Session(env["pg"]) as db, db.begin():
        original = tuple(
            dict(r)
            for r in db.execute(
                select(table).where(table.c.request_id == request_id)
            ).mappings()
        )
        db.execute(
            text("ALTER TABLE financial_payout_events DISABLE TRIGGER USER")
        )
        db.execute(
            update(table)
            .where(table.c.request_id == request_id)
            .values(
                details={"synthetic_private": "SYNTHETIC_PRIVATE_BROKEN_EVENT"}
            )
        )
        db.execute(
            text("ALTER TABLE financial_payout_events ENABLE TRIGGER USER")
        )
    try:
        detail = await service.detail(principal(env["client"]), request_id)
        assert detail["state"] == "unavailable" and detail["version"] is None
        assert detail["current_execution"] is None
        retained = detail["observation"]["retained_intents"]["entries"][0]
        assert retained["expected_version"] is None
        assert retained["version_provenance"] == "retained_version_required"
        assert "record_observation" in detail["allowed_actions"]
        assert "SYNTHETIC_PRIVATE" not in str(detail)
        own = await service.detail(
            principal(env["flow"]["manager"]), request_id
        )
        assert "SYNTHETIC_PRIVATE" not in str(own) and "fence" not in str(own)
        page = await service.own_page(principal(env["flow"]["manager"]))
        assert page["entries"][0]["state"] == "unavailable"
        with Session(env["pg"]) as db:
            assert db.scalar(
                select(table.c.details).where(
                    table.c.event_id == original[-1]["event_id"]
                )
            ) == {"synthetic_private": "SYNTHETIC_PRIVATE_BROKEN_EVENT"}
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                text("ALTER TABLE financial_payout_events DISABLE TRIGGER USER")
            )
            for row in original:
                db.execute(
                    update(table)
                    .where(table.c.event_id == row["event_id"])
                    .values(details=row["details"])
                )
            db.execute(
                text("ALTER TABLE financial_payout_events ENABLE TRIGGER USER")
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family",
    [
        "identity",
        "requirements",
        "requisites",
        "requests",
        "states",
        "events",
        "intents",
        "outcomes",
        "items",
    ],
)
async def test_actual_family_preflight_preserves_transaction_and_safe_absence(
    payout_env, family
):
    env = payout_env
    prepared = await prepare(env, amount=1)
    service, _, _, principal = runtime(env)
    owner, request_id = env["flow"]["manager"], UUID(prepared["request_id"])
    table = {
        "identity": "users",
        "requirements": "financial_payout_requirements",
        "requisites": "financial_payout_requisites",
        "requests": "financial_payout_requests",
        "states": "financial_payout_states",
        "events": "financial_payout_events",
        "intents": "financial_payout_intents",
        "outcomes": "financial_payout_outcomes",
        "items": "order_items",
    }[family]
    column = {"identity": "status", "items": "selection_state"}.get(family)
    with hidden_source(env, table, column):
        async with service.repository.snapshot() as snapshot:
            if family == "identity":
                with pytest.raises(
                    ValueError, match="payout_source_unavailable"
                ):
                    await snapshot.actor(principal(owner))
            elif family == "requirements":
                assert (
                    await snapshot.requirements(env["flow"]["clock"].at)
                ).source_blockers == ("payout_source_unavailable",)
                with pytest.raises(
                    ValueError, match="payout_source_unavailable"
                ):
                    await snapshot.requirements_page(Page(), None)
            elif family == "requests":
                for operation in (
                    snapshot.request(request_id, owner),
                    snapshot.requests(owner, Page(), None, queue=False),
                ):
                    with pytest.raises(
                        ValueError, match="payout_source_unavailable"
                    ):
                        await operation
                empty = await snapshot.financial(env["client"])
                assert empty.source_blockers == ("payout_source_unavailable",)
            elif family == "outcomes":
                with pytest.raises(
                    ValueError, match="payout_source_unavailable"
                ):
                    await snapshot.history(request_id, "outcomes", Page(), None)
            elif family == "items":
                assert await snapshot.item_blockers((env["flow"]["item"],)) == (
                    "payout_source_unavailable",
                )
            if family in ("requirements", "requisites"):
                assert (
                    await snapshot.requisite(
                        owner, UUID(env["requisites"]["requisites_id"])
                    )
                    is None
                )
                with pytest.raises(
                    ValueError, match="payout_source_unavailable"
                ):
                    await snapshot.requisites(owner, Page(), None)
            if family in ("states", "events", "intents", "requisites"):
                fact = await snapshot.request(request_id, owner)
                assert not fact.observation_ready
                if family == "intents":
                    assert not fact.retained_intents
                else:
                    assert not fact.consistent
            assert await snapshot.session.scalar(text("SELECT 42")) == 42


@pytest.mark.asyncio
async def test_actual_legacy_guard_stops_readiness_while_balance_remains_proven(
    payout_env,
):
    from ugc_bot.infrastructure.db.models import InteractionModel

    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    interaction = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            InteractionModel(
                interaction_id=interaction,
                order_id=env["order"],
                blogger_id=env["flow"]["creator"],
                advertiser_id=env["client"],
                status="issue",
            )
        )
        db.flush()
        db.execute(
            insert(Base.metadata.tables["legacy_financial_guards"]).values(
                user_id=env["flow"]["manager"],
                currency="RUB",
                interaction_id=interaction,
            )
        )
    context = await service.context(principal(env["flow"]["manager"]))
    assert context["financial"]["balances"]["available_minor"] == "59999"
    assert "legacy_payout_blocked" in context["recipient_blockers"]
    assert not context["capabilities"]["begin_request"]
    env["flow"]["clock"].at += timedelta(hours=72)
    detail = await service.detail(
        principal(env["client"]), UUID(state["request_id"])
    )
    assert "escalate" in detail["allowed_actions"]
    assert (await env["execute"](review_command(env, state, "escalate")))[
        "state"
    ] == "approved"


@pytest.mark.asyncio
async def test_actual_mismatched_allocation_scope_blocks_ordinary_actions(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    table, request_id = TABLE_MAP["allocations"], UUID(state["request_id"])
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            text("ALTER TABLE financial_payout_allocations DISABLE TRIGGER ALL")
        )
        db.execute(
            update(table)
            .where(table.c.request_id == request_id)
            .values(recipient_id=env["client"])
        )
        db.execute(
            text("ALTER TABLE financial_payout_allocations ENABLE TRIGGER ALL")
        )
    try:
        detail = await service.detail(principal(env["client"]), request_id)
        assert not {"review", "reject", "start"} & set(
            detail["allowed_actions"]
        )
        assert (
            "payout_allocation_source_unavailable"
            in detail["action_blockers"]["review"]
        )
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                text(
                    "ALTER TABLE financial_payout_allocations "
                    "DISABLE TRIGGER ALL"
                )
            )
            db.execute(
                update(table)
                .where(table.c.request_id == request_id)
                .values(recipient_id=env["flow"]["manager"])
            )
            db.execute(
                text(
                    "ALTER TABLE financial_payout_allocations "
                    "ENABLE TRIGGER ALL"
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,column",
    [
        ("financial_payout_commands", None),
        ("financial_payout_commands", "result"),
        ("users", "country"),
    ],
)
async def test_actual_common_sources_gate_every_ordinary_hint(
    payout_env, table, column
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    env["flow"]["clock"].at += timedelta(hours=72)
    with hidden_source(env, table, column):
        with pytest.raises(DBAPIError):
            await env["execute"](review_command(env, state, "escalate"))
        context = await service.context(principal(env["client"]))
        assert not context["capabilities"]["store_requisites"]
        assert not context["capabilities"]["publish_requirements"]
        detail = await service.detail(
            principal(env["client"]), UUID(state["request_id"])
        )
        assert "escalate" not in detail["allowed_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,column",
    [
        ("financial_obligations", "snapshot_id"),
        ("financial_wallets", "version"),
        ("order_items", "paid_item_id"),
    ],
)
async def test_actual_escalate_preflights_its_money_lock_queries(
    payout_env, table, column
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    env["flow"]["clock"].at += timedelta(hours=72)
    with hidden_source(env, table, column):
        with pytest.raises(DBAPIError):
            await env["execute"](review_command(env, state, "escalate"))
        context = await service.context(principal(env["client"]))
        assert context["capabilities"]["store_requisites"]
        assert context["capabilities"]["publish_requirements"]
        detail = await service.detail(
            principal(env["client"]), UUID(state["request_id"])
        )
        assert "escalate" not in detail["allowed_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,column",
    [
        ("financial_payout_terms_documents", "content_text"),
        ("financial_payout_requirement_contracts", "field_definitions"),
        ("financial_payout_requisites_acceptances", None),
    ],
)
async def test_actual_publication_sources_are_physical_prerequisites(
    payout_env, table, column
):
    env = payout_env
    service, _, _, principal = runtime(env)
    with hidden_source(env, table, column):
        context = await service.context(principal(env["client"]))
        assert not context["capabilities"]["publish_requirements"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    ["financial_movements", "financial_obligations", "financial_wallets"],
)
async def test_actual_store_and_publish_ignore_unrelated_money_sources(
    payout_env, table
):
    env = payout_env
    service, _, _, principal = runtime(env)
    with hidden_source(env, table):
        context = await service.context(principal(env["client"]))
        assert context["capabilities"]["store_requisites"]
        assert context["capabilities"]["publish_requirements"]
        stored = await env["execute"](
            replace(env["store"], operation_key="9gb-store-without-money")
        )
        assert stored["requisites_id"]
        published = await env["execute"](
            replace(
                env["publication"],
                operation_key="9gb-publish-without-money",
                expected_version=env["requirements"]["version"],
            )
        )
        assert published["readable"]


@pytest.mark.asyncio
async def test_actual_escalation_ignores_reconciliation_contents(payout_env):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    env["flow"]["clock"].at += timedelta(hours=72)
    table, owner = (
        Base.metadata.tables["financial_wallets"],
        env["flow"]["manager"],
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(table)
            .where(table.c.recipient_id == owner)
            .values(available_minor=59998)
        )
    try:
        context = await service.context(principal(owner))
        assert context["financial"]["state"] == "unavailable"
        detail = await service.detail(
            principal(env["client"]), UUID(state["request_id"])
        )
        assert "escalate" in detail["allowed_actions"]
        assert (await env["execute"](review_command(env, state, "escalate")))[
            "state"
        ] == "approved"
    finally:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(table)
                .where(table.c.recipient_id == owner)
                .values(available_minor=59999)
            )


@pytest.mark.asyncio
async def test_publication_needs_acceptance_relation_but_not_unused_columns(
    payout_env,
):
    env = payout_env
    service, _, _, principal = runtime(env)
    with hidden_source(
        env, "financial_payout_requisites_acceptances", "accepted"
    ):
        context = await service.context(principal(env["client"]))
        assert context["capabilities"]["publish_requirements"]
        assert not context["capabilities"]["store_requisites"]
        published = await env["execute"](
            replace(
                env["publication"],
                operation_key="9gb-publish-unused-acceptance",
                expected_version=env["requirements"]["version"],
            )
        )
        assert published["readable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "financial_movements",
        "legacy_financial_guards",
        "financial_collaborations",
    ],
)
async def test_escalation_ignores_sources_its_actual_writer_never_queries(
    payout_env, table
):
    env = payout_env
    service, _, _, principal = runtime(env)
    state = await env["execute"](request_command(env, amount_minor=1))
    state = await env["execute"](review_command(env, state, "review"))
    env["flow"]["clock"].at += timedelta(hours=72)
    with hidden_source(env, table):
        detail = await service.detail(
            principal(env["client"]), UUID(state["request_id"])
        )
        assert "escalate" in detail["allowed_actions"]
        assert (await env["execute"](review_command(env, state, "escalate")))[
            "state"
        ] == "approved"
