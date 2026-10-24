"""Actual signed Telegram/MAX principal to SQL draft and audience endpoints."""

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_campaign_drafts import (
    campaign_env as _campaign_env,
)
from tests.postgres_financial.test_campaign_drafts import configure, services
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router

campaign_env = _campaign_env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,prefix", [("telegram", "/miniapp/api"), ("max", "/api")]
)
async def test_signed_host_routes_persist_own_draft_and_truthful_preview(
    campaign_env, platform, prefix
):
    env = campaign_env
    await configure(env)
    container = env["container"]
    owner = env["users"]["owner"]
    foreign = env["users"]["foreign"]
    async with container.transaction_manager.transaction() as db:
        for user in (owner, foreign):
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(max_id=user.telegram_id, country="ru")
            )
    review, audience = services(env)
    app = FastAPI()
    app.state.config = container._config
    app.state.dispatcher = {
        **container.build_bot_services(),
        "campaign_review_service": review,
        "campaign_audience_service": audience,
    }
    app.include_router(
        router, prefix="/miniapp" if platform == "telegram" else ""
    )
    signed = {
        "platform": platform,
        "init_data": generate_init_data(
            "test-token", int(owner.telegram_id), "synthetic-owner"
        ),
    }
    payload = {
        **signed,
        "operation_key": "synthetic-asgi-" + uuid4().hex,
        "expected_version": 0,
        "policy_version": env["publication"]["version"],
        "terms_hash": env["settings"]["policy"]["terms_hash"],
        "content": {"title": "Task", "text": "Brief"},
        "segment": {},
    }
    path = prefix + "/campaigns/owned"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path + "/draft", json=payload)
        assert response.status_code == 200, response.text
        saved = response.json()
        UUID(saved["campaign_id"])
        result = await client.post(
            path + "/preview",
            json={
                **signed,
                "campaign_id": saved["campaign_id"],
                "revision_digest": saved["revision_digest"],
            },
        )
        assert (
            result.status_code == 200 and result.json()["eligible_count"] == 1
        )
        assert "telegram_id" not in result.text and "phone" not in result.text
        detail = await client.post(
            path + "/detail",
            json={**signed, "campaign_id": saved["campaign_id"]},
        )
        assert detail.status_code == 200 and detail.json()["content"] == {
            "title": "Task",
            "text": "Brief",
        }
        listed = await client.post(path + "/list", json=signed)
        assert (
            listed.status_code == 200
            and listed.json()["drafts"][0]["campaign_id"]
            == saved["campaign_id"]
        )
        foreign_signed = {
            "platform": platform,
            "init_data": generate_init_data(
                "test-token", int(foreign.telegram_id), "synthetic-foreign"
            ),
        }
        assert (
            await client.post(
                path + "/detail",
                json={**foreign_signed, "campaign_id": saved["campaign_id"]},
            )
        ).status_code == 404
        assert (
            await client.post(
                path + "/draft",
                json={**payload, "owner_id": str(foreign.user_id)},
            )
        ).status_code == 422
        assert (
            await client.post(
                path + "/list",
                json={
                    **signed,
                    "init_data": signed["init_data"] + "&auth_date=1",
                },
            )
        ).status_code == 401
