"""Finance routes use signed MiniApp identity, never body actors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.test_miniapp_auth import _make_valid_init_data
from ugc_bot.miniapp.api import router


def client_for(*, admin=True):
    actor = uuid4()
    service = SimpleNamespace(
        list_cases=AsyncMock(return_value=[{"version": 1}]),
        review=AsyncMock(return_value={"version": 2, "released": True}),
    )
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"), max_bot=None
    )
    app.state.dispatcher = {
        "user_role_service": SimpleNamespace(
            get_user=AsyncMock(
                return_value=SimpleNamespace(user_id=actor, country="ru")
            )
        ),
        "user_repo": SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(admin=admin))
        ),
        "legacy_financial_case_service": service,
    }
    return TestClient(app), service, actor


def test_signed_admin_can_list_and_review_case():
    client, service, actor = client_for()
    auth = {"init_data": _make_valid_init_data("test-token", 12345)}
    response = client.post("/api/finance/legacy-cases", json=auth)
    assert response.status_code == 200
    assert response.json() == [{"version": 1}]
    case_id, command = uuid4(), uuid4()
    response = client.post(
        f"/api/finance/legacy-cases/{case_id}/review",
        json={
            **auth,
            "expected_version": 1,
            "command_id": str(command),
            "decision": "release_no_adjustment",
            "reason": "Confirmed unchanged legacy result",
            "confirmed_result": True,
        },
    )
    assert response.status_code == 200
    assert service.review.call_args.kwargs["actor_id"] == actor
    assert service.review.call_args.kwargs["expected_version"] == 1


def test_invalid_signature_nonadmin_and_forged_actor_are_rejected():
    client, service, _ = client_for(admin=False)
    assert (
        client.post(
            "/api/finance/legacy-cases", json={"init_data": "forged"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/finance/legacy-cases",
            json={"init_data": _make_valid_init_data("test-token", 12345)},
        ).status_code
        == 403
    )
    service.list_cases.assert_not_awaited()
    client, service, _ = client_for()
    response = client.post(
        f"/api/finance/legacy-cases/{uuid4()}/review",
        json={
            "init_data": _make_valid_init_data("test-token", 12345),
            "actor_id": str(uuid4()),
            "admin": True,
            "expected_version": 1,
            "command_id": str(uuid4()),
            "decision": "release_no_adjustment",
            "reason": "x",
            "confirmed_result": True,
        },
    )
    assert response.status_code == 422
    service.review.assert_not_awaited()
