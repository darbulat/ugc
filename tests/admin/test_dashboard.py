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


def test_admin_creators_html_with_filters(monkeypatch) -> None:
    """Creators page renders with only_new and with_complaints filters."""
    creators = [
        {
            "user_id": "u1",
            "instagram_url": "https://instagram.com/u",
            "created_at": "2026-01-01",
            "has_complaints": True,
        }
    ]
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=creators,
        advertisers=[],
        orders=[],
        order_card={},
    )
    response = client.get(
        "/admin/users/creators?period=today&only_new=true&with_complaints=true"
    )
    assert response.status_code == 200
    assert "creators" in response.text.lower() or "Заказчики" in response.text


def test_admin_advertisers_html(monkeypatch) -> None:
    """Advertisers page renders with mocked data."""
    advertisers = [
        {"user_id": "a1", "brand": "Brand", "created_at": "2026-01-01"}
    ]
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=[],
        advertisers=advertisers,
        orders=[],
        order_card={},
    )
    response = client.get("/admin/users/advertisers")
    assert response.status_code == 200


def test_admin_orders_html_with_status_filter(monkeypatch) -> None:
    """Orders page renders with status filter."""
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
    response = client.get("/admin/orders?period=today&status=active")
    assert response.status_code == 200


def test_admin_order_detail_html(monkeypatch) -> None:
    """Order detail page renders when order exists."""
    from uuid import uuid4

    order_id = uuid4()
    order_card = {
        "order_id": str(order_id),
        "advertiser": "Brand",
        "description": "Test offer",
        "order_type": "ugc_only",
        "bloggers_needed": 3,
        "picked_count": 1,
        "progress": 0.33,
        "created_at": "2026-01-01T00:00:00",
        "completed_at": None,
        "status_label": "active",
        "status_age_hours": 12.0,
        "has_problem": False,
    }
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=[],
        advertisers=[],
        orders=[],
        order_card=order_card,
    )
    response = client.get(f"/admin/orders/{order_id}")
    assert response.status_code == 200


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


def test_admin_api_returns_401_when_not_authenticated(monkeypatch) -> None:
    """API routes return 401 when admin session is missing."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get("/admin/api/dashboard")
    assert response.status_code == 401


def test_admin_advertisers_redirect_when_not_authenticated(monkeypatch) -> None:
    """Advertisers page redirects to login when not authenticated."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get("/admin/users/advertisers", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/admin/login" in response.headers.get("location", "")


def test_admin_orders_redirect_when_not_authenticated(monkeypatch) -> None:
    """Orders page redirects to login when not authenticated."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get("/admin/orders", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/admin/login" in response.headers.get("location", "")


def test_admin_orders_with_status_filter(monkeypatch) -> None:
    """Orders API passes status filter to list_orders."""
    list_orders_mock = AsyncMock(
        return_value=[
            {
                "order_id": "order-1",
                "advertiser": "Brand",
                "status_label": "closed",
                "picked_count": 1,
                "needed_count": 3,
                "created_at": "2026-01-01T00:00:00",
                "status_age_hours": 12.0,
                "has_problem": False,
            }
        ]
    )
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        list_orders_mock,
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value={}),
    )

    app = create_admin_app()
    client = TestClient(app)
    response = client.get("/admin/api/orders?period=today&status=closed")
    assert response.status_code == 200
    list_orders_mock.assert_called_once_with(
        period="today", status_filter="closed"
    )


def test_admin_order_detail_redirect_when_not_authenticated(
    monkeypatch,
) -> None:
    """Order detail page redirects to login when not authenticated."""
    from uuid import uuid4

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(
        f"/admin/orders/{uuid4()}",
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert "/admin/login" in response.headers.get("location", "")


def test_order_model_edit_redirects_when_not_authenticated(
    monkeypatch,
) -> None:
    """SQLAdmin order-model edit redirects to login when not authenticated."""
    from uuid import uuid4

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    order_id = uuid4()
    response = client.get(
        f"/admin/order-model/edit/{order_id}",
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert "/admin/login" in response.headers.get("location", "")


def test_admin_order_detail_404_when_not_found(monkeypatch) -> None:
    """Order detail page returns 404 when order not found."""
    from uuid import uuid4

    order_id = uuid4()
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=[]),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/orders/{order_id}")
    assert response.status_code == 404


def test_admin_creators_api_with_complaints_filter(monkeypatch) -> None:
    """Creators API passes with_complaints to list_creators."""
    creators = [
        {
            "user_id": "u1",
            "instagram_url": "https://instagram.com/u",
            "created_at": "2026-01-01",
            "has_complaints": True,
        }
    ]
    list_creators_mock = AsyncMock(return_value=creators)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        list_creators_mock,
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value={}),
    )

    app = create_admin_app()
    client = TestClient(app)
    response = client.get(
        "/admin/api/users/creators?period=today&with_complaints=true"
    )
    assert response.status_code == 200
    assert response.json() == {"items": creators}
    list_creators_mock.assert_called_once_with(
        period="today",
        only_new=False,
        only_with_complaints=True,
    )


def test_admin_advertisers_api(monkeypatch) -> None:
    """Advertisers API returns list."""
    advertisers = [
        {"user_id": "a1", "brand": "Brand", "created_at": "2026-01-01"}
    ]
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=[],
        advertisers=advertisers,
        orders=[],
        order_card={},
    )
    response = client.get("/admin/api/users/advertisers")
    assert response.status_code == 200
    assert response.json() == {"items": advertisers}


def test_admin_order_api_404_when_not_found(monkeypatch) -> None:
    """Order API returns 404 when order not found."""
    from uuid import uuid4

    order_id = uuid4()
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=[]),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/api/orders/{order_id}")
    assert response.status_code == 404
