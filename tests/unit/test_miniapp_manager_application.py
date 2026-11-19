"""Native onboarding preserves signed ownership and application rules."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.manager_application_api import (
    create_manager_application_router,
)

BASE = "/manager/application"


class ConstraintError(Exception):
    def __init__(self, constraint_name):
        super().__init__("constraint violation")
        self.diag = SimpleNamespace(constraint_name=constraint_name)


@pytest.mark.asyncio
async def test_duplicate_instagram_returns_validation_response(
    application_client,
):
    from sqlalchemy.exc import IntegrityError

    client, service, _, _, _, _ = application_client
    original = ConstraintError("manager_applications_instagram_user_id_key")
    service.answer.side_effect = IntegrityError("UPDATE", {}, original)
    response = await client.post(
        BASE + "/answer",
        json=auth() | {"field": "instagram", "value": "example"},
    )
    assert response.status_code == 422
    assert "Instagram" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "original"),
    [
        ("instagram", ConstraintError("different_constraint")),
        ("instagram", Exception("missing diagnostics")),
        ("name", ConstraintError("manager_applications_instagram_user_id_key")),
    ],
)
async def test_unrelated_integrity_error_is_not_suppressed(
    application_client, field, original
):
    from sqlalchemy.exc import IntegrityError

    client, service, _, _, _, _ = application_client
    service.answer.side_effect = IntegrityError("UPDATE", {}, original)
    with pytest.raises(IntegrityError):
        await client.post(
            BASE + "/answer",
            json=auth() | {"field": field, "value": "example"},
        )


@pytest_asyncio.fixture
async def application_client():
    users = {
        key: SimpleNamespace(user_id=uuid4(), telegram_id=key)
        for key in ("101", "202")
    }
    row = {
        "user_id": users["101"].user_id,
        "answers": {"name": "Анна"},
        "state": "draft",
        "instagram_verified_at": None,
        "decision_note": "Internal review only",
        "challenge": "private-old-code",
    }
    service = SimpleNamespace(
        open=AsyncMock(return_value=row),
        answer=AsyncMock(return_value=row),
        instagram_challenge=AsyncMock(return_value="UMCM-000000000001"),
    )
    cities = SimpleNamespace(
        resolve_city_identity=AsyncMock(
            return_value=("Казань", "Татарстан", "Россия")
        )
    )
    app = FastAPI()
    app.include_router(
        create_manager_application_router(resolve_financial_principal)
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"),
        max_bot=None,
        instagram=SimpleNamespace(admin_instagram_username="@umc.test"),
    )

    async def get_user(external, messenger):
        return users.get(external)

    app.state.dispatcher = {
        "user_role_service": SimpleNamespace(get_user=get_user),
        "manager_applications": service,
        "blogger_registration_service": cities,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, service, row, users, cities, app


def auth(external=101):
    return {
        "init_data": generate_init_data("test-token", external, "candidate"),
        "platform": "telegram",
    }


@pytest.mark.asyncio
async def test_view_resumes_own_answers_without_internal_review_data(
    application_client,
):
    client, service, _, users, _, _ = application_client
    response = await client.post(BASE + "/view", json=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["answers"] == {"name": "Анна"}
    assert data["next_field"] == "rate"
    assert "Internal review" not in response.text
    assert "private-old-code" not in response.text
    assert "user_id" not in data
    assert "decision_note" not in data
    assert data["instagram_code"] is None
    service.open.assert_awaited_once_with(users["101"].user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"init_data": "forged", "platform": "telegram"},
        auth() | {"platform": "max"},
        auth() | {"user_id": str(uuid4())},
        auth() | {"state": "approved"},
        auth(303),
    ],
)
async def test_invalid_or_spoofed_requests_never_open_application(
    application_client, payload
):
    client, service, _, _, _, _ = application_client
    response = await client.post(BASE + "/view", json=payload)
    assert response.status_code in (401, 403, 404, 422)
    assert response.headers["cache-control"] == "no-store"
    service.open.assert_not_awaited()
    service.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_uses_authenticated_owner_and_server_city_identity(
    application_client,
):
    client, service, _, users, cities, _ = application_client
    response = await client.post(
        BASE + "/answer",
        json=auth(202) | {"field": "location", "value": " Казань "},
    )
    assert response.status_code == 200
    cities.resolve_city_identity.assert_awaited_once_with("Казань")
    service.answer.assert_awaited_once_with(
        users["202"].user_id,
        "location",
        "Казань",
        location_context=("Татарстан", "Россия"),
    )


@pytest.mark.asyncio
async def test_city_failure_and_unknown_field_cannot_save_answer(
    application_client,
):
    client, service, _, _, cities, _ = application_client
    cities.resolve_city_identity.return_value = None
    for field in ("location", "instagram_verified_at", "coverage"):
        response = await client.post(
            BASE + "/answer",
            json=auth() | {"field": field, "value": "Unknown"},
        )
        assert response.status_code == 422
    service.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_submission_preserves_review_and_instagram_verification(
    application_client,
):
    client, service, row, _, _, _ = application_client
    row["state"] = "submitted"
    row["answers"]["instagram"] = "candidate"
    response = await client.post(BASE + "/view", json=auth())
    assert response.json()["state"] == "submitted"
    assert response.json()["instagram_code"] == "UMCM-000000000001"
    assert response.json()["instagram_direct_url"] == "https://ig.me/m/umc.test"
    service.answer.side_effect = ValueError("Заявка уже на рассмотрении.")
    response = await client.post(
        BASE + "/answer", json=auth() | {"field": "name", "value": "Анна"}
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    row["instagram_verified_at"] = "verified"
    response = await client.post(BASE + "/view", json=auth())
    assert response.json()["instagram_verified"] is True
    assert response.json()["instagram_code"] is None


@pytest.mark.asyncio
async def test_city_preview_validates_query_without_changing_answers(
    application_client,
):
    client, service, _, _, _, _ = application_client
    response = await client.post(
        BASE + "/city", json=auth() | {"value": "Казань"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "city": "Казань",
        "region": "Татарстан",
        "country": "Россия",
    }
    response = await client.post(
        BASE + "/city", json=auth() | {"value": "12345"}
    )
    assert response.status_code == 422
    response = await client.post(BASE + "/view?user_id=other", json=auth())
    assert response.status_code == 422
    service.open.assert_not_awaited()
    service.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_service_returns_retryable_error(application_client):
    client, service, _, _, _, app = application_client
    app.state.dispatcher["manager_applications"] = None
    response = await client.post(BASE + "/view", json=auth())
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    service.open.assert_not_awaited()
