"""Real signed override approval feeds a production captured-payment worker."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.financial_worker import process_until_published
from tests.postgres_financial.test_client_entitlement_runtime import (
    capture,
    processor,
    rows,
    seed_attribution,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

capture_env = _capture_env
PATH = "/miniapp/api/admin/rate-overrides"


def application(container, config):
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = container.build_bot_services()
    return app


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_approved_api_rate_is_used_at_capture_and_survives_admin_demotion(
    request,
):
    env = request.getfixturevalue("capture_env")
    partner, _ = seed_attribution(env)
    external = str(uuid4().int % 10**12 + 1)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == partner)
            .values(admin=True, telegram_id=external)
        )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "FINANCIAL_CORE_ENABLED": True,
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    first, second = Container(config), Container(config)
    try:
        app = application(first, config)
        now = datetime.now(timezone.utc)
        # Control only the server's approval clock, to test a past approval
        # followed by a new captured payment without waiting in real time.
        app.state.dispatcher["rate_override_service"].clock = SimpleNamespace(
            now=lambda: now - timedelta(minutes=5)
        )
        auth = {
            "init_data": generate_init_data(
                "test-token", int(external), "synthetic-admin"
            )
        }
        command = {
            **auth,
            "action": "create",
            "operation_key": f"rate:{partner}",
            "recipient_id": str(partner),
            "side": "client",
            "policy_version": env["version"],
            "rate_bps": 2000,
            "effective_from": (now - timedelta(minutes=4)).isoformat(),
            "effective_until": (now + timedelta(days=30)).isoformat(),
            "reason": "synthetic individually agreed client rate",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(PATH + "/command", json=command)
            assert response.status_code == 200, response.text
            approval = response.json()["override"]
            override_id = approval["approval"]["override_id"]
            assert approval["approval"]["approved_by"] == str(partner)
        event_id = await capture(env)
        await process_until_published(processor(env), env["pg"], [event_id])
        snapshots = rows(env, "rate_snapshots")
        assert {r["rate_bps"] for r in snapshots} == {2000}
        assert {r["rate_source"] for r in snapshots} == {"override"}
        assert {str(r["override_id"]) for r in snapshots} == {override_id}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application(second, config)),
            base_url="http://testserver",
        ) as client:
            read = await client.post(PATH + f"/{override_id}/status", json=auth)
            assert read.status_code == 200
            assert read.json() == approval
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == partner)
                    .values(admin=False)
                )
            denied = await client.post(
                PATH + f"/{override_id}/status", json=auth
            )
            assert denied.status_code == 403
            replay = await client.post(PATH + "/command", json=command)
            assert replay.status_code == 403
        assert rows(env, "rate_snapshots") == snapshots
        assert len(rows(env, "financial_obligations")) == 2
        assert len(rows(env, "financial_movements")) == 2
    finally:
        for container in (first, second):
            await container.session_factory.kw["bind"].dispose()
