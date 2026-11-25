from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.config import AppConfig
from ugc_bot.miniapp.api import router
from ugc_bot.telegram_webhook_app import _init_browser_checkout


@pytest.mark.parametrize("service", [None, "consultation"])
@pytest.mark.parametrize(
    "route, failure, status, state",
    [
        ("status", None, 200, "available"),
        ("status", LookupError(), 200, "unavailable"),
        ("start", None, 200, "pending"),
        ("start", LookupError(), 200, "unavailable"),
        (
            "start",
            OrderCreationError("browser_receipt_email_required"),
            422,
            None,
        ),
        (
            "start",
            OrderCreationError("telegram_payment_pending"),
            200,
            "telegram_pending",
        ),
        (
            "start",
            OrderCreationError("browser_payment_quote_expiring"),
            200,
            "unavailable",
        ),
    ],
)
def test_bearer_link_checkout_does_not_require_messenger_session(
    route,
    service,
    failure,
    status,
    state,
):
    token = uuid4()
    checkout = SimpleNamespace(
        start=AsyncMock(side_effect=failure if route == "start" else None),
        buyer_view=AsyncMock(
            side_effect=failure if route == "status" else None,
            return_value={
                "state": state if state != "unavailable" else "available"
            },
        ),
    )
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    container = SimpleNamespace(
        build_browser_checkout=Mock(return_value=None if service else checkout),
        build_consultation_checkout=Mock(
            return_value=checkout if service else None
        ),
    )
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "synthetic", "YOOKASSA_BROWSER_SHOP_ID": "123"}
    )
    _init_browser_checkout(app, {"container": container}, config)
    client = TestClient(app)
    response = client.post(
        f"/miniapp/api/browser-payment/{route}",
        json={
            "token": str(token),
            "email": "buyer@example.test",
            "service": service,
        },
    )
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    if state is None:
        assert response.json() == {
            "error": "Укажите корректный email для чека."
        }
    else:
        assert response.json() == {"state": state}
    if route == "start":
        checkout.start.assert_awaited_once_with(token, "buyer@example.test")
    else:
        checkout.start.assert_not_awaited()


@pytest.mark.parametrize("route", ["status", "start"])
def test_browser_payment_unavailable_without_merchant_configuration(route):
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    _init_browser_checkout(
        app, {}, AppConfig.model_validate({"BOT_TOKEN": "synthetic"})
    )
    client = TestClient(app)
    response = client.post(
        f"/miniapp/api/browser-payment/{route}",
        json={"token": str(uuid4()), "email": "buyer@example.test"},
    )
    assert response.json() == {"state": "unavailable"}
