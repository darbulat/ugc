"""Signed social editing survives a new production container and SQL session."""

from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router


@pytest.mark.asyncio
async def test_signed_social_roundtrip_survives_container_rebuild(
    financial_pg_engine,
):
    external_id, max_id = (str(uuid4().int % 10**12 + 1) for _ in range(2))
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "MAX_BOT_TOKEN": "max-test-token",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    first, second = Container(config), Container(config)
    try:
        repos = first.build_repos()
        user = await create_test_user(
            repos["user_repo"], external_id=external_id
        )
        profile = await create_test_blogger_profile(
            repos["blogger_repo"], user.user_id, confirmed=True
        )
        await repos["blogger_repo"].save(
            replace(profile, instagram_user_id="ig-" + external_id)
        )
        async with first.session_factory.begin() as db:
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == user.user_id)
                .values(max_id=max_id)
            )
        body = {
            "init_data": generate_init_data(
                "test-token", int(external_id), "creator"
            )
        }

        max_body = {
            "platform": "max",
            "init_data": generate_init_data(
                "max-test-token", int(max_id), "creator"
            ),
        }

        def app(container):
            value = FastAPI()
            value.include_router(router, prefix="/miniapp")
            value.state.config = config
            value.state.dispatcher = container.build_bot_services()
            return value

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(first)),
            base_url="http://testserver",
        ) as client:
            before = await client.post(
                "/miniapp/api/social/accounts", json=body
            )
            assert before.status_code == 200 and before.json()["show_prompt"]
            dismissed = await client.post(
                "/miniapp/api/social/prompt/dismiss", json=body
            )
            assert dismissed.json() == {"dismissed": True}
            cross_host = await client.post(
                "/miniapp/api/social/accounts", json=max_body
            )
            assert cross_host.status_code == 200
            assert cross_host.json()["show_prompt"] is False
            dismiss_again = await client.post(
                "/miniapp/api/social/prompt/dismiss", json=max_body
            )
            assert dismiss_again.status_code == 200
            assert dismiss_again.json() == {"dismissed": True}
            saved = await client.post(
                "/miniapp/api/social/accounts/save",
                json={
                    **body,
                    "network": "youtube",
                    "url": "https://youtube.com/@creator",
                    "reported_followers": 1200,
                },
            )
            assert saved.status_code == 200
            account_id = saved.json()["account"]["account_id"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(second)),
            base_url="http://testserver",
        ) as client:
            listed = await client.post(
                "/miniapp/api/social/accounts", json=body
            )
            assert listed.status_code == 200
            accounts = listed.json()["accounts"]
            youtube = next(a for a in accounts if a["platform"] == "youtube")
            assert youtube["account_id"] == account_id
            assert youtube["verified"] is False
            assert youtube["followers_count"] == 1200
            assert youtube["metrics_source"] == "creator_self_reported"
            assert youtube["metrics_fetched_at"]
            assert listed.json()["show_prompt"] is False
            for invalid in (True, -1, 1.5, "1000"):
                invalid_report = await client.post(
                    "/miniapp/api/social/accounts/save",
                    json={
                        **max_body,
                        "network": "youtube",
                        "url": "https://youtube.com/@creator",
                        "reported_followers": invalid,
                    },
                )
                assert invalid_report.status_code == 422
            same_link = await client.post(
                "/miniapp/api/social/accounts/save",
                json={
                    **max_body,
                    "network": "youtube",
                    "url": "https://youtube.com/@creator",
                },
            )
            assert same_link.status_code == 200
            assert same_link.json()["account"]["followers_count"] == 1200
            saved_from_max = await client.post(
                "/miniapp/api/social/accounts/save",
                json={
                    **max_body,
                    "network": "youtube",
                    "url": "https://youtube.com/@creator",
                    "reported_followers": 0,
                },
            )
            assert saved_from_max.status_code == 200
            from_telegram = await client.post(
                "/miniapp/api/social/accounts", json=body
            )
            account = next(
                a
                for a in from_telegram.json()["accounts"]
                if a["account_id"] == account_id
            )
            assert account["followers_count"] == 0
            assert account["metrics_source"] == "creator_self_reported"
            updated = await client.post(
                "/miniapp/api/social/accounts/save",
                json={
                    **max_body,
                    "network": "youtube",
                    "url": "https://youtube.com/@updated",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["account"]["followers_count"] is None
            assert updated.json()["account"]["metrics_source"] is None
            removed = await client.post(
                "/miniapp/api/social/accounts/remove",
                json={**body, "account_id": account_id},
            )
            assert removed.status_code == 200
            assert removed.json()["removed"] is True
        assert (
            await repos["social_account_repo"].list_accounts(user.user_id) == []
        )
    finally:
        for container in (first, second):
            await container.session_factory.kw["bind"].dispose()
