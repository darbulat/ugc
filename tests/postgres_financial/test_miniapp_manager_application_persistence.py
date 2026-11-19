"""Native manager onboarding shares durable bot answers and review."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
)
from ugc_bot.domain.manager_application import MANAGER_SUBMITTED
from ugc_bot.infrastructure.db.models import OutboxEventModel
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    ManagerApplications,
)
from ugc_bot.miniapp.api import router

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
async def test_native_application_resumes_bot_draft_and_submits_to_review(
    intake_env,
):
    env = intake_env
    user = env["user"]
    service = ManagerApplications(env["container"].transaction_manager, None)
    await service.open(user.user_id)
    await service.answer(user.user_id, "name", "Анна")
    services = env["container"].build_bot_services()
    services["manager_applications"] = service
    services["blogger_registration_service"] = SimpleNamespace(
        resolve_city_identity=AsyncMock(
            return_value=("Казань", "Татарстан", "Россия")
        )
    )
    env["config"].instagram.admin_instagram_username = "umc.test"
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = env["config"]
    app.state.dispatcher = services
    auth = {
        "init_data": generate_init_data(
            "test-token", int(user.telegram_id), "candidate"
        ),
        "platform": "telegram",
    }
    base = "/miniapp/api/manager/application"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(base + "/view", json=auth)
        assert response.status_code == 200
        assert response.json()["answers"] == {"name": "Анна"}
        assert response.json()["next_field"] == "rate"
        values = {
            "rate": "1500–2000",
            "work_format": "Фрилансер",
            "weekly_capacity": "11–30",
            "location": "Казань",
            "phone": "+79991234567",
            "instagram": "native_candidate",
            "settlement": "Самозанятый",
            "case": "Согласовала съёмку и публикации с десятью авторами.",
            "shortfall_plan": "Найду авторов по геометкам и проверю аудиторию.",
        }
        for field, value in values.items():
            response = await client.post(
                base + "/answer", json=auth | {"field": field, "value": value}
            )
            assert response.status_code == 200, response.text
        assert response.json()["state"] == "submitted"
        code = response.json()["instagram_code"]
        assert code.startswith("UMCM-")
        assert response.json()["instagram_verified"] is False
        reopened = await client.post(base + "/view", json=auth)
        assert reopened.json()["instagram_code"] == code
        duplicate = await client.post(
            base + "/answer",
            json=auth
            | {"field": "shortfall_plan", "value": values["shortfall_plan"]},
        )
        assert duplicate.status_code == 422

    persisted = await service.open(user.user_id)
    assert persisted["state"] == "submitted"
    assert persisted["answers"]["location_country"] == "Россия"
    assert persisted["answers"]["rate"] == "1500–2000"
    assert persisted["instagram_verified_at"] is None
    with Session(env["pg"]) as db:
        events = db.scalars(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(user.user_id),
                OutboxEventModel.event_type == MANAGER_SUBMITTED,
            )
        ).all()
        assert len(events) == 2
