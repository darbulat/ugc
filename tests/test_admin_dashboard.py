"""Tests for admin dashboard routes."""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ugc_bot.admin.app import create_admin_app
from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import AdminDashboardService


def _build_admin_client(
    monkeypatch,  # type: ignore[no-untyped-def]
    *,
    dashboard_payload: dict[str, Any],
    creators: list[dict[str, Any]],
    advertisers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    order_card: dict[str, Any],
) -> TestClient:
    """Create admin TestClient with mocked dashboard service."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value=dashboard_payload),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        AsyncMock(return_value=creators),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=advertisers),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=orders),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value=order_card),
    )
    app = create_admin_app()
    return TestClient(app)


def test_admin_dashboard_html(monkeypatch) -> None:
    """HTML dashboard renders with mocked data."""
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={
            "period": "today",
            "registrations": {
                "creators": {"count": 1, "change_pct": 10.0},
                "advertisers": {"count": 2, "change_pct": -5.0},
            },
            "orders": {"active": 3, "completed": 1, "archived": 0},
            "problems": {"open_complaints": 0, "delays": 0},
            "delayed_orders": [],
        },
        creators=[],
        advertisers=[],
        orders=[],
        order_card={"order_id": "x"},
    )
    response = client.get("/admin/dashboard?period=today")
    assert response.status_code == 200
    assert "Дашборд" in response.text


def test_admin_dashboard_api(monkeypatch) -> None:
    """Dashboard API returns payload."""
    payload = {
        "period": "today",
        "registrations": {"creators": {"count": 0, "change_pct": None}},
        "orders": {"active": 0, "completed": 0, "archived": 0},
        "problems": {"open_complaints": 0, "delays": 0},
        "delayed_orders": [],
    }
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload=payload,
        creators=[],
        advertisers=[],
        orders=[],
        order_card={"order_id": "x"},
    )
    response = client.get("/admin/api/dashboard?period=today")
    assert response.status_code == 200
    assert response.json() == payload


def test_admin_orders_api(monkeypatch) -> None:
    """Orders API returns list items."""
    orders = [
        {
            "order_id": "order-1",
            "advertiser": "Brand",
            "status_label": "active",
            "picked_count": 1,
            "needed_count": 3,
            "created_at": "2026-01-01T00:00:00",
            "status_age_hours": 12.0,
            "has_problem": False,
        }
    ]
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=[],
        advertisers=[],
        orders=orders,
        order_card={"order_id": "order-1"},
    )
    response = client.get("/admin/api/orders?period=today")
    assert response.status_code == 200
    assert response.json() == {"items": orders}
