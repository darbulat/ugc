"""Real previous-revision behavior and lossless campaign schema roundtrip."""

import os
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import insert, select, text, update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.financial_environment import isolated_financial_database
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.campaign_models import COMMANDS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    UserReferralBindingModel,
)
from ugc_bot.miniapp.api import router


def migrate(engine, action, target):
    env = os.environ.copy()
    env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, target],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.asyncio
async def test_previous_schema_setup_and_guarded_roundtrip(
    financial_pg_engine,
):
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="paid_selection_delivery_v1",
    ) as engine:
        config = AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "DATABASE_URL": engine.url.render_as_string(
                    hide_password=False
                ),
                "KAFKA_ENABLED": False,
                "USE_REDIS_STORAGE": False,
                "REDIS_URL": "",
            }
        )
        container = Container(config)
        repos = container.build_repos()
        users = {}
        for role in ("creator", "owner", "admin"):
            users[role] = await create_test_user(
                repos["user_repo"],
                external_id=str(uuid4().int % 10**12 + 1),
                admin=role == "admin",
            )
        for role in ("creator", "owner"):
            await create_test_blogger_profile(
                repos["blogger_repo"],
                users[role].user_id,
                instagram_url="https://instagram.com/synthetic_" + uuid4().hex,
            )
        async with container.transaction_manager.transaction() as db:
            await db.execute(
                update(BloggerProfileModel)
                .values(instagram_user_id="canonical-migration-" + uuid4().hex)
                .where(BloggerProfileModel.user_id == users["creator"].user_id)
            )
            await db.execute(
                insert(UserReferralBindingModel).values(
                    referrer_user_id=users["owner"].user_id,
                    referred_user_id=users["creator"].user_id,
                )
            )
        app = FastAPI()
        app.include_router(router, prefix="/miniapp")
        app.state.config = config
        app.state.dispatcher = container.build_bot_services()

        def body(role):
            return {
                "init_data": generate_init_data(
                    "test-token", int(users[role].telegram_id), "synthetic"
                ),
                "platform": "telegram",
            }

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                assert (
                    await client.post(
                        "/miniapp/api/campaigns/settings", json=body("creator")
                    )
                ).status_code == 503
                up = migrate(engine, "upgrade", "campaign_foundation_v1")
                assert up.returncode == 0, up.stderr
                current = await client.post(
                    "/miniapp/api/campaigns/settings", json=body("creator")
                )
                assert current.status_code == 200, current.text
                assert (
                    current.json()["consent_unavailable_reason"]
                    == "policy_missing"
                    and current.json()["policy"] is None
                    and not current.json()["consent"]["effective"]
                )
                assert current.json()["inviter"]["label"].startswith(
                    "https://instagram.com/synthetic_"
                )
                suspend = await client.post(
                    "/miniapp/api/campaigns/policy/suspend",
                    json={
                        **body("admin"),
                        "operation_key": "synthetic-no-policy",
                        "expected_version": 0,
                        "reason": "Cannot suspend an absent policy",
                    },
                )
                assert suspend.status_code == 409
                grant = await client.post(
                    "/miniapp/api/campaigns/publishers/grant",
                    json={
                        **body("admin"),
                        "operation_key": "synthetic-no-policy-grant",
                        "expected_version": 0,
                        "owner_id": str(users["owner"].user_id),
                        "reason": "Missing published policy",
                    },
                )
                assert grant.status_code == 409
            down = migrate(engine, "downgrade", "paid_selection_delivery_v1")
            assert down.returncode == 0, down.stderr
            up = migrate(engine, "upgrade", "campaign_foundation_v1")
            assert up.returncode == 0, up.stderr
            async with container.transaction_manager.transaction() as db:
                await db.execute(
                    insert(COMMANDS).values(
                        actor_id=users["creator"].user_id,
                        operation_key="synthetic-retention-proof",
                        action="unsubscribe",
                        payload_hash="a" * 64,
                        recorded_at=text("now()"),
                        result={"synthetic": "retention-boundary"},
                    )
                )
            denied = migrate(engine, "downgrade", "paid_selection_delivery_v1")
            assert (
                denied.returncode != 0
                and "Cannot discard immutable campaign history" in denied.stderr
            )
            async with container.transaction_manager.transaction() as db:
                assert (
                    await db.scalar(select(COMMANDS.c.operation_key))
                    == "synthetic-retention-proof"
                )
        finally:
            await container.session_factory.kw["bind"].dispose()
