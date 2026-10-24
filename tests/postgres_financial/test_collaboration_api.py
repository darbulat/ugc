"""Public signed commands persist through the production dependency graph."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_collaboration_persistence import (
    collaboration_pg as collaboration_pg,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationNoticeModel,
)
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router


@pytest.mark.asyncio
@pytest.mark.usefixtures("collaboration_pg")
async def test_public_work_commands_survive_rebuilt_container(
    request,
    financial_pg_engine,
):
    factory, _, _, _, data = request.getfixturevalue("collaboration_pg")
    identities = {
        role: str(uuid4().int % 10**12 + 1) for role in ("client", "creator")
    }
    async with factory.begin() as db:
        for role, external in identities.items():
            await db.execute(
                update(UserModel)
                .where(UserModel.user_id == data[role])
                .values(telegram_id=external)
            )
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "FINANCIAL_CORE_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    containers = [Container(config), Container(config)]

    def app(container):
        value = FastAPI()
        value.include_router(router, prefix="/miniapp")
        value.state.config = config
        value.state.dispatcher = container.build_bot_services()
        return value

    def auth(role):
        return {
            "init_data": generate_init_data(
                "test-token", int(identities[role]), role
            )
        }

    path = f"/miniapp/api/collaborations/{data['assignment']}"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(containers[0])),
            base_url="http://testserver",
        ) as client:
            for version, role, action, extra in (
                (
                    0,
                    "client",
                    "assign",
                    {
                        "due_at": (
                            datetime.now(timezone.utc) + timedelta(days=2)
                        ).isoformat(),
                        "terms_reference": "synthetic client brief consent",
                    },
                ),
                (1, "client", "start", {}),
                (
                    2,
                    "creator",
                    "claim",
                    {"evidence": "https://example.com/proof"},
                ),
            ):
                response = await client.post(
                    path + "/command",
                    json={
                        **auth(role),
                        "action": action,
                        "operation_key": action,
                        "expected_version": version,
                        **extra,
                    },
                )
                assert response.status_code == 200, response.text
            claimed = response.json()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(containers[1])),
            base_url="http://testserver",
        ) as client:
            status = await client.post(path + "/status", json=auth("client"))
            assert status.status_code == 200
            assert status.json()["record"] == claimed["record"]
            assert status.json()["actor_id"] == str(data["client"])
            assert set(status.json()["allowed_actions"]) == {
                "agree",
                "dispute",
                "extend_due",
            }
            agreed = await client.post(
                path + "/command",
                json={
                    **auth("client"),
                    "action": "agree",
                    "operation_key": "agree",
                    "expected_version": 3,
                },
            )
            assert agreed.status_code == 200
            assert (
                agreed.json()["record"]["collaboration"]["state"]
                == "success_final"
            )
            assert agreed.json()["available_at"] is not None
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(CollaborationEventModel)
                    .where(
                        CollaborationEventModel.assignment_id
                        == data["assignment"]
                    )
                )
                == 4
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(CollaborationNoticeModel)
                    .where(
                        CollaborationNoticeModel.assignment_id
                        == data["assignment"]
                    )
                )
                == 1
            )
    finally:
        for container in containers:
            await container.dispose()
