"""The signed feedback endpoint binds writes to the resolved customer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp import api


@pytest.fixture
def endpoint(monkeypatch):
    principal = AuthenticatedMessengerPrincipal(uuid4(), "telegram", "123456")
    resolver = AsyncMock(return_value=principal)
    monkeypatch.setattr(api, "resolve_financial_principal", resolver)
    service = SimpleNamespace(record_supplemental_feedback=AsyncMock())
    app = FastAPI()
    app.include_router(api.router, prefix="/miniapp")
    app.state.dispatcher = {"blogger_rating_service": service}
    body = dict(
        init_data="signed-synthetic",
        order_id=str(uuid4()),
        creator_id=str(uuid4()),
        feedback="worked",
    )
    with TestClient(app) as client:
        yield client, app, service, resolver, principal, body


def test_feedback_uses_resolved_actor_and_complete_creator_scope(endpoint):
    client, _, service, resolver, principal, body = endpoint
    response = client.post(
        "/miniapp/api/customer/orders/creator-feedback", json=body
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    args = service.record_supplemental_feedback.call_args
    assert args.args[0] == principal.user_id
    assert str(args.args[1]) == body["order_id"]
    assert str(args.args[2]) == body["creator_id"]
    assert args.args[3] == "worked" and args.kwargs["principal"] == principal
    assert resolver.call_args.args[1] == "signed-synthetic"


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("rating_access_denied"),
        ValueError("rating_participant_required"),
    ],
)
def test_feedback_rejects_unauthorized_or_unrelated_creator(endpoint, error):
    client, _, service, _, _, body = endpoint
    service.record_supplemental_feedback.side_effect = error
    response = client.post(
        "/miniapp/api/customer/orders/creator-feedback", json=body
    )
    assert response.status_code == 403


def test_feedback_returns_unavailable_without_a_service(endpoint):
    client, app, _, _, _, body = endpoint
    app.state.dispatcher = {}
    assert (
        client.post(
            "/miniapp/api/customer/orders/creator-feedback", json=body
        ).status_code
        == 503
    )


@pytest.mark.parametrize(
    "forged",
    [
        {"actor_id": str(uuid4())},
        {"feedback": "success_final"},
        {"platform": "web"},
    ],
)
def test_feedback_rejects_actor_override_and_financial_status(endpoint, forged):
    client, _, service, resolver, _, body = endpoint
    assert (
        client.post(
            "/miniapp/api/customer/orders/creator-feedback", json=body | forged
        ).status_code
        == 422
    )
    service.record_supplemental_feedback.assert_not_awaited()
    resolver.assert_not_awaited()
