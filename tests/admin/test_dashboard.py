"""Tests for admin dashboard routes."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ugc_bot.admin.app import create_admin_app
from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import AdminDashboardService
from ugc_bot.infrastructure.redis_cache import (
    serialize_admin_payload,
)

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
    monkeypatch.setattr(
        AdminDashboardService,
        "get_creators_by_city",
        AsyncMock(return_value=[]),
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
    assert "Админка" in response.text
    assert 'href="/admin/"' in response.text


def test_admin_dashboard_mvp_redirects_to_dashboard(monkeypatch) -> None:
    """dashboard-mvp redirects to /admin/dashboard without intermediate page."""
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={
            "period": "today",
            "registrations": {"creators": {}, "advertisers": {}},
            "orders": {},
            "problems": {},
            "delayed_orders": [],
            "open_complaints_list": [],
            "turnover_period": 0,
            "referrals": {},
            "payout_requests": [],
        },
        creators=[],
        advertisers=[],
        orders=[],
        order_card={},
    )
    response = client.get("/admin/dashboard-mvp", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers.get("location") == "/admin/dashboard"


def test_admin_creators_page_creators_by_city_section(monkeypatch) -> None:
    """Creators page renders Креаторы по городам section below pagination."""
    get_creators_by_city_mock = AsyncMock(
        return_value=[
            {"city": "Moscow", "count": 5},
            {"city": "", "count": 2},
        ]
    )
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload={},
        creators=[],
        advertisers=[],
        orders=[],
        order_card={"order_id": "x"},
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_creators_by_city",
        get_creators_by_city_mock,
    )
    response = client.get("/admin/users/creators?period=today")
    assert response.status_code == 200
    assert "Креаторы по городам" in response.text
    assert "Moscow" in response.text
    assert "Не указан" in response.text
    assert "5" in response.text
    assert "2" in response.text
    get_creators_by_city_mock.assert_called_once()


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


def test_dashboard_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second request returns cached response; get_dashboard called once."""
    cached_payload = {"period": "today", "cached": True, "orders": {}}
    serialized = serialize_admin_payload(cached_payload)

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()

    get_dashboard_mock = AsyncMock(
        return_value={"period": "today", "orders": {}}
    )
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        get_dashboard_mock,
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

    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)

    r1 = client.get("/admin/api/dashboard?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/dashboard?period=today")
    assert r2.status_code == 200
    assert r2.json() == cached_payload
    assert get_dashboard_mock.call_count == 1


def test_dashboard_charts_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Charts API cache hit; get_dashboard_charts called once."""
    cached_charts = {"series": [], "labels": []}
    serialized = serialize_admin_payload(cached_charts)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    get_charts_mock = AsyncMock(return_value={"series": [], "labels": []})
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard_charts",
        get_charts_mock,
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/api/dashboard/charts?period=7d")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/dashboard/charts?period=7d")
    assert r2.status_code == 200
    assert r2.json() == cached_charts
    assert get_charts_mock.call_count == 1


def test_creators_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creators API cache hit on second request; list_creators called once."""
    cached = _paginated([{"user_id": "u1", "nickname": "c1"}])
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    list_creators_mock = AsyncMock(return_value=_paginated([]))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        list_creators_mock,
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/api/users/creators?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/users/creators?period=today")
    assert r2.status_code == 200
    assert r2.json() == cached
    assert list_creators_mock.call_count == 1


def test_search_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search API cache hit on second request; search_users called once."""
    cached = {"query": "x", "users": []}
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "search_users",
        search_mock,
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/api/search?q=x")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/search?q=x")
    assert r2.status_code == 200
    assert r2.json() == cached
    assert search_mock.call_count == 1


def test_orders_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orders API cache hit on second request; list_orders called once."""
    cached = _paginated([{"order_id": "o1", "status_label": "active"}])
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    list_orders_mock = AsyncMock(return_value=_paginated([]))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        list_orders_mock,
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
        "get_order_card",
        AsyncMock(return_value={}),
    )
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/api/orders?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/orders?period=today")
    assert r2.status_code == 200
    assert r2.json() == cached
    assert list_orders_mock.call_count == 1


def test_dashboard_html_uses_cache_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dashboard HTML cache hit on second request; get_dashboard called once."""
    payload = {
        "period": "today",
        "registrations": {
            "creators": {"count": 0, "change_pct": 0.0},
            "advertisers": {"count": 0, "change_pct": 0.0},
        },
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
    serialized = serialize_admin_payload(payload)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    get_dashboard_mock = AsyncMock(return_value=payload)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        get_dashboard_mock,
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/dashboard?period=today")
    assert r1.status_code == 200
    assert "Дашборд" in r1.text
    r2 = client.get("/admin/dashboard?period=today")
    assert r2.status_code == 200
    assert get_dashboard_mock.call_count == 1


def test_referrers_html_uses_cache_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Referrers HTML cache hit on second request; get_dashboard called once."""
    payload = {
        "period": "today",
        "registrations": {
            "creators": {"count": 0, "change_pct": 0.0},
            "advertisers": {"count": 0, "change_pct": 0.0},
        },
        "orders": {"active": 0, "completed": 0, "archived": 0},
        "problems": {"open_complaints": 0, "delays": 0},
        "delayed_orders": [],
        "open_complaints_list": [],
        "turnover_period": 0,
        "referrals": {
            "referrers": [],
            "referrers_total": 0,
            "referrers_page": 1,
            "referrers_per_page": 25,
            "referrers_total_pages": 1,
            "total_earned": None,
            "total_balance": None,
        },
        "payout_requests": [],
    }
    serialized = serialize_admin_payload(payload)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    get_dashboard_mock = AsyncMock(return_value=payload)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        get_dashboard_mock,
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/referrers?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/referrers?period=today")
    assert r2.status_code == 200
    assert get_dashboard_mock.call_count == 1


def test_advertisers_api_returns_cached_response_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advertisers API cache hit on second request; list_advertisers once."""
    cached = _paginated([{"user_id": "a1", "nickname": "adv1"}])
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    list_adv_mock = AsyncMock(return_value=_paginated([]))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "list_advertisers",
        list_adv_mock,
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
        "list_orders",
        AsyncMock(return_value=_paginated([])),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_card",
        AsyncMock(return_value={}),
    )
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/api/users/advertisers")
    assert r1.status_code == 200
    r2 = client.get("/admin/api/users/advertisers")
    assert r2.status_code == 200
    assert r2.json() == cached
    assert list_adv_mock.call_count == 1


def test_admin_search_html_uses_cache_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search HTML cache hit on second request; search_users called once."""
    cached = {"query": "q", "users": [{"user_id": "u1", "nickname": "u1"}]}
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "search_users",
        search_mock,
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
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/search?q=q")
    assert r1.status_code == 200
    r2 = client.get("/admin/search?q=q")
    assert r2.status_code == 200
    assert search_mock.call_count == 1


def test_admin_creators_html_uses_cache_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creators list HTML cache hit on second request; list_creators once."""
    cached = _paginated([{"user_id": "c1", "nickname": "creator1"}])
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    list_creators_mock = AsyncMock(return_value=_paginated([]))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "list_creators",
        list_creators_mock,
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(return_value={}),
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
    monkeypatch.setattr(
        AdminDashboardService,
        "get_creators_by_city",
        AsyncMock(return_value=[]),
    )
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/users/creators?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/users/creators?period=today")
    assert r2.status_code == 200
    assert list_creators_mock.call_count == 1


def test_admin_orders_html_uses_cache_on_second_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orders list HTML cache hit on second request; list_orders once."""
    cached = _paginated([{"order_id": "o1", "status_label": "active"}])
    serialized = serialize_admin_payload(cached)
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=[None, serialized])
    mock_cache.set = AsyncMock()
    list_orders_mock = AsyncMock(return_value=_paginated([]))
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET", _TEST_ADMIN_SECRET)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))
    monkeypatch.setattr(
        AdminDashboardService,
        "list_orders",
        list_orders_mock,
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
        "get_order_card",
        AsyncMock(return_value={}),
    )
    with patch(
        "ugc_bot.admin.app.AdminCache",
        MagicMock(return_value=mock_cache),
    ):
        app = create_admin_app()
    client = TestClient(app)
    r1 = client.get("/admin/orders?period=today")
    assert r1.status_code == 200
    r2 = client.get("/admin/orders?period=today")
    assert r2.status_code == 200
    assert list_orders_mock.call_count == 1


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
