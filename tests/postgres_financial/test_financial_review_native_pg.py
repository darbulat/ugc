"""Signed native review preserves actual paid referral history."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_financial_reviews import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_financial_reviews import (
    financial_pg_engine as financial_pg_engine,
)
from tests.postgres_financial.test_financial_reviews import (
    partner_payout,
)
from tests.postgres_financial.test_financial_reviews import (
    payout_env as payout_env,
)
from ugc_bot.config import MaxBotConfig
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

__all__ = ["capture_env", "financial_pg_engine", "payout_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_late_paid_review_cas_replay_and_current_admin(
    platform, payout_env
):
    env = payout_env
    partner = await partner_payout(env)
    container = env["flow"]["container"]
    config = env["config"]
    config.max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-review-max")
    external = str(uuid4().int % 10**12 + 1)
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(telegram_id=external, max_id=external)
        )
        ground_key = db.scalar(
            select(obligations.c.business_key).where(
                obligations.c.recipient_id == partner,
                obligations.c.kind == "creator_referral",
            )
        )
    assert ground_key
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = container.build_bot_services()
    app.state.dispatcher["financial_review_service"].clock = env[
        "service"
    ].clock
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            config.bot.bot_token
            if platform == "telegram"
            else "synthetic-review-max",
            int(external),
            "synthetic-admin",
        ),
    )
    prefix = "/miniapp/api/financial/reviews/admin"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def post(path, values=auth):
            return await client.post(prefix + path, json=values)

        response = await post("/context", auth | dict(business_key=ground_key))
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        ground = response.json()["grounds"][0]
        assert ground["buckets"]["paid"] == "5000"
        opened_body = auth | dict(
            operation_key="signed-late-open:" + uuid4().hex,
            business_key=ground_key,
            expected_source_hash=ground["current_source_hash"],
            reason="Synthetic independently reviewed late evidence",
            evidence_reference="synthetic:late-proof",
            evidence_hash="a" * 64,
        )
        assert (
            await post(
                "/open", opened_body | dict(expected_source_hash="0" * 64)
            )
        ).status_code == 409
        response = await post("/open", opened_body)
        assert response.status_code == 200, response.text
        opened = response.json()
        assert opened["state"] == "open" and opened["buckets"]["paid"] == "5000"
        assert (await post("/open", opened_body)).json() == opened
        resolving = auth | dict(
            operation_key="signed-late-resolve:" + uuid4().hex,
            case_id=opened["case_id"],
            expected_version=opened["version"],
            expected_source_hash=opened["current_source_hash"],
            decision="cumulative_cancel",
            target_minor="2000",
            reason="Synthetic late review cancels proven portion",
            evidence_reference="synthetic:late-decision",
            evidence_hash="b" * 64,
        )
        assert (
            await post("/resolve", resolving | dict(expected_version=99))
        ).status_code == 409
        assert (
            await post(
                "/resolve", resolving | dict(expected_source_hash="0" * 64)
            )
        ).status_code == 409
        response = await post("/resolve", resolving)
        assert response.status_code == 200, response.text
        resolved = response.json()
        assert resolved["buckets"]["paid"] == "5000"
        assert resolved["buckets"]["debt"] == "2000"
        assert (
            resolved["target_minor"] == resolved["debt_created_minor"] == "2000"
        )
        assert (await post("/resolve", resolving)).json() == resolved
        response = await post("/context", auth | dict(business_key=ground_key))
        assert response.json()["grounds"][0]["buckets"]["debt"] == "2000"
        assert (await post("/" + opened["case_id"] + "/view")).json()[
            "state"
        ] == "resolved"
        assert (
            await post("/open", opened_body | dict(actor_id=str(env["client"])))
        ).status_code == 422
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["client"])
                .values(admin=False)
            )
        for path, values in (
            ("/context", auth),
            ("/open", opened_body),
            ("/resolve", resolving),
            ("/" + opened["case_id"] + "/view", auth),
        ):
            response = await post(path, values)
            assert response.status_code == 403, response.text
            assert "synthetic:late-proof" not in response.text
