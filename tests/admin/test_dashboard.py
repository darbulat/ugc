"""Tests for admin dashboard routes."""

from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ugc_bot.admin.app import create_admin_app
from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import AdminDashboardService

# Strong admin credentials for tests (not in config _WEAK_ADMIN_VALUES).
_TEST_ADMIN_PASSWORD = "Str0ng-Test-P@ssw0rd"
_TEST_ADMIN_SECRET = "test-s3cr3t-k3y-min-32-chars-long"


def _paginated(items: list[dict[str, Any]], total: int | None = None) -> dict:
    """Paginated response for list_creators / list_advertisers / list_orders."""
    n = total if total is not None else len(items)
    total_pages = max(1, (n + 24) // 25) if n else 1
    return {
        "items": items,
        "total": n,
        "page": 1,
        "per_page": 25,
        "total_pages": total_pages,
    }


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
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
        AsyncMock(return_value=_paginated(creators)),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=_paginated(advertisers)),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=_paginated(orders)),
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
            "open_complaints_list": [],
            "turnover_period": 0,
            "referrals": {
                "referrers": [],
                "total_earned": None,
                "total_balance": None,
            },
            "payout_requests": [],
        },
        creators=[],
        advertisers=[],
        orders=[],
        order_card={"order_id": "x"},
    )
    response = client.get("/admin/dashboard?period=today")
    assert response.status_code == 200
    assert "Дашборд" in response.text


def test_admin_referrers_html(monkeypatch) -> None:
    """Referrers page renders with mocked data."""
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={
            "registrations": {},
            "orders": {},
            "problems": {},
            "delayed_orders": [],
            "open_complaints_list": [],
            "turnover_period": None,
            "referrals": {
                "referrers": [
                    {
                        "user_id": "u1",
                        "telegram": "@m",
                        "referral_code": "r1",
                        "balance": 10.0,
                        "total_referred": 2,
                        "referred_creators": 1,
                        "referred_advertisers": 1,
                        "new_in_period": 0,
                    }
                ],
                "referrers_total": 1,
                "referrers_page": 1,
                "referrers_per_page": 25,
                "referrers_total_pages": 1,
                "referrers_sort": "balance",
                "referrers_order": "desc",
                "referrers_filter": "all",
                "total_earned": 100.0,
                "total_balance": 50.0,
            },
            "payout_requests": [],
        },
        creators=[],
        advertisers=[],
        orders=[],
        order_card={},
    )
    response = client.get("/admin/referrers?period=today")
    assert response.status_code == 200
    assert "Рефералы" in response.text


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
        "open_complaints_list": [],
        "turnover_period": 0,
        "referrals": {
            "referrers": [],
            "total_earned": None,
            "total_balance": None,
        },
        "payout_requests": [],
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
    """Orders API returns paginated list."""
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
    data = response.json()
    assert data["items"] == orders
    assert data["total"] == 1
    assert "page" in data
    assert "per_page" in data
    assert "total_pages" in data


def test_admin_api_returns_401_when_not_authenticated(monkeypatch) -> None:
    """API routes return 401 when admin session is missing."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
    orders = [
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
    list_orders_mock = AsyncMock(return_value=_paginated(orders))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=_paginated([])),
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
        period="today",
        status_filter="closed",
        page=1,
        per_page=25,
        sort="created_at",
        order="desc",
    )


def test_admin_order_detail_redirect_when_not_authenticated(
    monkeypatch,
) -> None:
    """Order detail page redirects to login when not authenticated."""
    from uuid import uuid4

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=_paginated([])),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/orders/{order_id}")
    assert response.status_code == 404


def test_admin_user_card_html(monkeypatch) -> None:
    """User card page renders with mocked user data."""
    from uuid import uuid4

    user_id = uuid4()
    user_card = {
        "user_id": str(user_id),
        "username": "john",
        "telegram": "@john",
        "external_id": "ext1",
        "status": "active",
        "blogger_profile": None,
        "advertiser_profile": None,
    }
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_user_card",
        AsyncMock(return_value=user_card),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value={}),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/users/{user_id}")
    assert response.status_code == 200
    assert "Карточка пользователя" in response.text
    assert "@john" in response.text


def test_admin_user_card_redirect_when_not_authenticated(
    monkeypatch,
) -> None:
    """User card page redirects to login when not authenticated."""
    from uuid import uuid4

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(
        AdminAuth, "authenticate", AsyncMock(return_value=False)
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(
        f"/admin/users/{uuid4()}",
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert "/admin/login" in response.headers.get("location", "")


def test_admin_user_card_404_when_not_found(monkeypatch) -> None:
    """User card page returns 404 when user not found."""
    from uuid import uuid4

    user_id = uuid4()
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_user_card",
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
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value={}),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/users/{user_id}")
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
    list_creators_mock = AsyncMock(return_value=_paginated(creators))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=_paginated([])),
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
    assert response.json()["items"] == creators
    list_creators_mock.assert_called_once_with(
        period="today",
        only_new=False,
        only_with_complaints=True,
        page=1,
        per_page=25,
        q=None,
        sort="created_at",
        order="desc",
    )


def test_admin_advertisers_api(monkeypatch) -> None:
    """Advertisers API returns paginated list."""
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
    data = response.json()
    assert data["items"] == advertisers
    assert data["total"] == 1
    assert "page" in data
    assert "per_page" in data
    assert "total_pages" in data


def test_admin_order_api_404_when_not_found(monkeypatch) -> None:
    """Order API returns 404 when order not found."""
    from uuid import uuid4

    order_id = uuid4()
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
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
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        AsyncMock(return_value=_paginated([])),
    )

    app = create_admin_app()
    client = TestClient(app)

    response = client.get(f"/admin/api/orders/{order_id}")
    assert response.status_code == 404


def test_admin_dashboard_charts_api(monkeypatch) -> None:
    """Charts API returns time-series data as JSON."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    charts_data = {
        "registrations_creators": [{"date": "2026-02-01", "count": 5}],
        "registrations_advertisers": [{"date": "2026-02-01", "count": 2}],
        "orders": [{"date": "2026-02-01", "count": 3}],
        "turnover": [{"date": "2026-02-01", "amount": 100.0}],
    }
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard_charts",
        AsyncMock(return_value=charts_data),
    )
    app = create_admin_app()
    client = TestClient(app)
    response = client.get("/admin/api/dashboard/charts?period=7d")
    assert response.status_code == 200
    data = response.json()
    assert "registrations_creators" in data
    assert data["orders"][0]["count"] == 3


def test_admin_search_api(monkeypatch) -> None:
    """Search API returns users as JSON."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "search_users",
        AsyncMock(return_value=[{"user_id": "u1", "username": "john"}]),
    )
    app = create_admin_app()
    client = TestClient(app)
    response = client.get("/admin/api/search?q=john")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "john"
    assert len(data["users"]) == 1
    assert data["users"][0]["username"] == "john"


def test_admin_search_page_html(monkeypatch) -> None:
    """Search page renders with query and users."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "search_users",
        AsyncMock(return_value=[{"user_id": "u1", "username": "jane"}]),
    )
    app = create_admin_app()
    client = TestClient(app)
    response = client.get("/admin/search?q=jane")
    assert response.status_code == 200
    assert "jane" in response.text or "search" in response.text.lower()
