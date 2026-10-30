"""Saved quote context and authenticated bound-image preview remain private."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ugc_bot.admin import app as module
from ugc_bot.config import AppConfig


def order():
    return NS(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        product_photo_file_id="order-image:" + str(uuid4()),
    )


@pytest.mark.asyncio
async def test_quote_injection_uses_saved_service_and_decimal_amounts(
    monkeypatch,
):
    current = order()
    details = dict(
        contact_reference="<protected-client>",
        position_count=10,
        accompaniment_count=2,
        format="with_manager",
        currency="RUB",
        selection_base_minor=500000,
        accompaniment_minor=240000,
        total_minor=740000,
    )
    projection = NS(for_order=AsyncMock(return_value=details))
    monkeypatch.setattr(
        module,
        "_get_admin_container",
        lambda: NS(build_order_notice_details_service=lambda: projection),
    )
    context = {}
    await module._inject_order_quote_details(
        context, module.OrderAdmin(), current
    )
    assert context["order_quote_details"]["total_display"] == "7400.00"
    assert context["order_quote_details"]["selection_base_display"] == "5000.00"
    assert (
        context["order_quote_details"]["contact_reference"]
        == "<protected-client>"
    )
    assert (
        context["order_image_preview"]
        == f"/admin/order-images/{current.order_id}"
    )
    projection.for_order.assert_awaited_once_with(current)
    untouched = {}
    await module._inject_order_quote_details(
        untouched, module.UserAdmin(), current
    )
    await module._inject_order_quote_details(
        untouched, module.OrderAdmin(), None
    )
    assert untouched == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["no-container", "no-service", "legacy-order"])
async def test_quote_injection_has_safe_legacy_fallback(monkeypatch, kind):
    current = order()
    current.product_photo_file_id = "legacy-telegram-id"
    container = (
        None
        if kind == "no-container"
        else NS(
            build_order_notice_details_service=lambda: (
                None
                if kind == "no-service"
                else NS(for_order=AsyncMock(return_value=None))
            )
        )
    )
    monkeypatch.setattr(module, "_get_admin_container", lambda: container)
    context = {}
    await module._inject_order_quote_details(
        context, module.OrderAdmin(), current
    )
    assert context == {"order_quote_details": None, "order_image_preview": None}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        "ok",
        "unauthenticated",
        "unavailable",
        "missing-order",
        "mismatch",
        "integrity",
        "missing-file",
    ],
)
async def test_preview_handler_authenticates_before_access_and_never_caches(
    result,
):
    current = order()
    auth = NS(authenticate=AsyncMock(return_value=result != "unauthenticated"))
    service = NS(attached_content=AsyncMock(return_value=b"private-jpeg"))
    if result in ("mismatch", "integrity", "missing-file"):
        service.attached_content.side_effect = {
            "mismatch": LookupError(),
            "integrity": ValueError(),
            "missing-file": FileNotFoundError(),
        }[result]
    repository = NS(
        get_by_id=AsyncMock(
            return_value=None if result == "missing-order" else current
        )
    )
    container = NS(
        build_order_image_service=Mock(
            return_value=None if result == "unavailable" else service
        ),
        build_repos=Mock(return_value={"order_repo": repository}),
    )
    response = await module._handle_order_image_preview(
        object(), auth, container, current.order_id
    )
    assert response.status_code == {
        "ok": 200,
        "unauthenticated": 401,
        "unavailable": 503,
    }.get(result, 404)
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    if result == "ok":
        assert response.body == b"private-jpeg"
        assert response.media_type == "image/jpeg"
    if result == "unauthenticated":
        container.build_order_image_service.assert_not_called()
        container.build_repos.assert_not_called()


def test_preview_route_requires_real_admin_login_session(monkeypatch):
    current = order()
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "DATABASE_URL": "sqlite:///:memory:",
            "KAFKA_ENABLED": False,
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "Strong-Test-Password42!",
            "ADMIN_SECRET": "a-strong-test-session-secret-32-characters",
        }
    )
    container = NS(
        get_admin_engine=lambda: create_engine("sqlite:///:memory:"),
        session_factory=None,
        transaction_manager=None,
        dispose=AsyncMock(),
        build_order_image_service=Mock(
            return_value=NS(
                attached_content=AsyncMock(return_value=b"private-jpeg")
            )
        ),
        build_repos=lambda: {
            "order_repo": NS(get_by_id=AsyncMock(return_value=current))
        },
    )
    monkeypatch.setattr(module, "load_config", lambda: config)
    monkeypatch.setattr(module, "Container", lambda _: container)
    client = TestClient(module.create_admin_app())
    path = f"/admin/order-images/{current.order_id}"
    assert client.get(path).status_code == 401
    container.build_order_image_service.assert_not_called()
    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "Strong-Test-Password42!"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    image = client.get(path)
    assert image.status_code == 200 and image.content == b"private-jpeg"
