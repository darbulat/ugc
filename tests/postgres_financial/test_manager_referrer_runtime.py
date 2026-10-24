"""One actual person can earn distinct referral and management grounds."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    finish_work,
    obligations,
    process_work_events,
    start_flow,
    wallet,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

capture_env = _capture_env


@pytest.mark.asyncio
async def test_actual_manager_and_both_referral_sides_have_separate_history(
    capture_env,
    monkeypatch,
):
    env = capture_env
    flow = await start_flow(env, monkeypatch, same_manager_partner=True)
    container = flow["container"]
    try:
        await finish_work(env, flow)
        await process_work_events(env, flow)
        assert flow["partner"] == flow["manager"]
        balance = wallet(env, flow["manager"])
        assert balance["pending_minor"] == 10000
        assert balance["hold_minor"] == 65000
        own = [
            row
            for row in obligations(env)
            if row["recipient_id"] == flow["manager"]
        ]
        assert len(own) == 4
        assert {row["kind"] for row in own} == {
            "client_referral",
            "creator_referral",
            "management",
        }
        assert len({row["business_key"] for row in own}) == 4
        external = str(uuid4().int % 10**12 + 1)
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == flow["manager"])
                .values(telegram_id=external)
            )
        app = FastAPI()
        app.include_router(router, prefix="/miniapp")
        app.state.config = container._config
        app.state.dispatcher = container.build_bot_services()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/miniapp/api/partner/view",
                json={
                    "init_data": generate_init_data(
                        "test-token", int(external), "manager-partner"
                    )
                },
            )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["actor_id"] == str(flow["manager"])
        finance = data["financial"]
        assert finance["state"] == "ready"
        groups = {row["kind"]: row["balances"] for row in finance["groups"]}
        assert groups["management"]["hold"] == "60000"
        assert groups["creator_referral"]["hold"] == "5000"
        assert groups["client_referral"]["pending"] == "10000"
        assert {row["kind"] for row in finance["history"]["entries"]} == set(
            groups
        )
    finally:
        await container.dispose()
