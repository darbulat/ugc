"""Actual grants preserve prices and their approved hold."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_financial_completion import (
    completion as completion,
)
from tests.postgres_financial.test_order_intake import intake_env as intake_env
from ugc_bot.application.manual_grant_ports import (
    ApproveManualGrant,
    ManualGrantAuthority,
)
from ugc_bot.container.manual_grant_factory import build_manual_grants
from ugc_bot.domain.corrections import correction_payload_hash
from ugc_bot.infrastructure.db.base import Base

__all__ = ["completion", "intake_env"]


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial PostgreSQL required")
    with isolated_financial_database(
        url,
        target_revision="0116_manual_grants",
        current_order_model=True,
    ) as engine:
        yield engine


def scenario(completion):
    rt, _ = completion
    env = rt.env
    env["config"].financial.superadmin_user_ids_raw = str(env["admin"].user_id)
    service, sweep = build_manual_grants(
        env["config"], env["container"].transaction_manager
    )
    service.clock = env["clock"]
    command = ApproveManualGrant(
        actor_id=env["admin"].user_id,
        operation_key="actual-positive-" + uuid4().hex,
        paid_item_id=rt.facts["order"].items[0].paid_item_id,
        recipient_id=rt.facts["partner"],
        amount_minor=12345,
        currency="RUB",
        reason="Superadmin reviews a missing commission supplement",
        evidence_reference="synthetic-private:grant-review",
        evidence_hash="d" * 64,
    )
    return rt, service, sweep, command


@pytest.mark.asyncio
async def test_real_superadmin_grant_hold_replay_and_14_day_sweep(completion):
    rt, service, sweep, command = scenario(completion)
    env, tm = rt.env, rt.env["container"].transaction_manager
    principal = rt.principal(command.actor_id)
    async with tm.transaction() as db:
        granted = await service.approve(
            command, session=db, principal=principal
        )
        assert (
            await service.approve(command, session=db, principal=principal)
            == granted
        )
        original = await service.ledger.repository.get_issue(
            "manual-grant:" + granted["grant_id"], session=db
        )
        assert original.basis.kind == "manual_adjustment"
        assert original.basis.rate_bps is original.basis.verified_count is None
        money = await service.ledger.repository.read_projection(
            command.recipient_id, "RUB", session=db
        )
        assert money["hold"] == 12345 and money["available"] == 0
        assert not (
            await service.mature(
                UUID(granted["grant_id"]),
                session=db,
                actor_id=command.actor_id,
                principal=principal,
            )
        )["mature"]
    movements = Base.metadata.tables["financial_movements"]
    with pytest.raises(IntegrityError, match="manual_grant_hold_required"):
        async with tm.transaction() as db:
            from ugc_bot.application.financial_ports import JournalMovement

            await service.ledger.repository.append(
                JournalMovement(
                    obligation_id=original.obligation_id,
                    operation_key="forged-early-release",
                    event_id=granted["grant_id"],
                    movement_type="transfer",
                    amount_minor=12345,
                    currency="RUB",
                    effective_at=env["clock"].at,
                    recorded_at=env["clock"].at,
                    actor_id=command.actor_id,
                    actor_kind="admin",
                    reason="Attempted early release",
                    bucket_from="hold",
                    bucket_to="available",
                ),
                session=db,
            )
    env["clock"].at += timedelta(days=14)
    assert (await sweep.run_once())["matured"] == 1
    assert (await sweep.run_once())["attempted"] == 0
    async with tm.transaction() as db:
        money = await service.ledger.repository.read_projection(
            command.recipient_id, "RUB", session=db
        )
        assert money["available"] == 12345 and money["hold"] == 0
    with Session(env["pg"]) as db:
        items = Base.metadata.tables["order_items"]
        prices = db.execute(
            select(items.c.selection_minor, items.c.accompaniment_minor).where(
                items.c.order_id == rt.facts["order"].order_id
            )
        ).all()
        assert all(
            selection == 50000 and accompaniment == 0
            for selection, accompaniment in prices
        )
        journal = (
            db.execute(
                select(movements).where(
                    movements.c.obligation_id == original.obligation_id
                )
            )
            .mappings()
            .all()
        )
    assert len(journal) == 3


@pytest.mark.asyncio
async def test_sql_rejects_grant_with_forged_superadmin_authority(
    completion, monkeypatch
):
    rt, service, _, command = scenario(completion)
    original_append = service.repository.append_grant

    async def faulty_authority(fact, *, session):
        bad = dict(fact, authority={"superadmin_user_ids": []})
        bad["authority_hash"] = correction_payload_hash(
            ManualGrantAuthority(())
        )
        await original_append(bad, session=session)

    monkeypatch.setattr(service.repository, "append_grant", faulty_authority)
    with pytest.raises(IntegrityError, match="manual_grant_source_mismatch"):
        async with rt.env["container"].transaction_manager.transaction() as db:
            await service.approve(
                command, session=db, principal=rt.principal(command.actor_id)
            )
    with Session(rt.env["pg"]) as db:
        table = Base.metadata.tables["financial_manual_grants"]
        assert not db.execute(
            select(table).where(table.c.paid_item_id == command.paid_item_id)
        ).first()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ("telegram", "max"))
async def test_signed_superadmin_endpoint_checks_current_authority(
    completion, platform
):
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import update

    from tests.e2e.miniapp_helpers import generate_init_data
    from ugc_bot.config import MaxBotConfig
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.miniapp.api import router

    rt, service, _, command = scenario(completion)
    env = rt.env
    env["config"].max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-max-token")
    external = str(uuid4().int % 10**12 + 1)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == command.actor_id)
            .values(telegram_id=external, max_id=external)
        )
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = env["config"]
    app.state.dispatcher = env["container"].build_bot_services()
    app.state.dispatcher["manual_grant_service"] = service
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            "test-token" if platform == "telegram" else "synthetic-max-token",
            int(external),
            "synthetic",
        ),
    )
    body = auth | dict(
        operation_key=command.operation_key,
        paid_item_id=str(command.paid_item_id),
        recipient_id=str(command.recipient_id),
        amount_minor="12345",
        currency="RUB",
        reason=command.reason,
        evidence_reference=command.evidence_reference,
        evidence_hash=command.evidence_hash,
    )
    path = "/miniapp/api/financial/grants/admin"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        context = await client.post(path + "/context", json=auth)
        assert context.status_code == 200, context.text
        assert context.json()["can_approve"]
        response = await client.post(path + "/approve", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["amount_minor"] == "12345" and result["state"] == "hold"
        assert (
            await client.post(path + "/approve", json=body)
        ).json() == result
        mature = await client.post(
            path + "/mature", json=auth | {"grant_id": result["grant_id"]}
        )
        assert mature.status_code == 200 and not mature.json()["mature"]
        assert (
            await client.post(
                path + "/approve",
                json=body | {"actor_id": str(command.actor_id)},
            )
        ).status_code == 422
        service.superadmins = frozenset()
        assert (
            await client.post(path + "/approve", json=body)
        ).status_code == 403
        # Removed authority cannot probe for missing grant sources.
        assert (
            await client.post(
                path + "/mature", json=auth | {"grant_id": str(uuid4())}
            )
        ).status_code == 403
        service.superadmins = {command.actor_id}
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == command.actor_id)
                .values(admin=False)
            )
        assert (
            await client.post(path + "/approve", json=body)
        ).status_code == 403
