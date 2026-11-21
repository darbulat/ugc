"""Dashboard order cards with synthetic data and real templates/assets."""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from playwright.sync_api import expect

from tests.admin.test_dashboard import _build_admin_client
from tests.e2e.test_miniapp_design_system import screenshot
from ugc_bot.admin.dashboard_service import AdminDashboardService

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(45)]
BASE = "http://testserver"
ORDER_ID = "11111111-1111-1111-1111-111111111111"
MANAGER_ID = "22222222-2222-2222-2222-222222222222"


def test_order_cards_share_manager_and_status_layout(page, monkeypatch):
    row = {
        "order_id": ORDER_ID,
        "advertiser": "City Squash",
        "offer_text": "Индивидуальная тренировка по сквошу за видео",
        "created_at": datetime(2026, 11, 10, 13, 28, tzinfo=UTC),
        "age_hours": 66,
        "days_since_payment": 9.8,
        "selection_days": 3,
        "days_until_selection_due": -6.8,
        "selection_due_at": datetime(2026, 11, 13, 12, 52, tzinfo=UTC),
        "picked_count": 2,
        "needed_count": 10,
        "transferred_count": 6,
        "manual_transferred_count": 4,
        "reasons": ["active_overdue", "low_picked"],
        "managers": [
            {"id": MANAGER_ID, "name": "Sh_renetta", "telegram": "@sh_renetta"}
        ],
    }
    payload = {
        "registrations": {
            "creators": {"count": 0},
            "advertisers": {"count": 0},
        },
        "problems": {"open_complaints": 0},
        "order_attention": {
            "active": 2,
            "delayed": [row],
            "moderation": [
                dict(
                    row,
                    offer_text="Ищем авторов от 7 000 подписчиков",
                    reasons=["waiting_moderation"],
                    managers=[
                        dict(
                            id=MANAGER_ID,
                            name="Рената · ответственный менеджер",
                            telegram="@sh_renetta",
                        ),
                        dict(id=ORDER_ID, name="Анна", telegram=None),
                    ],
                )
            ],
            "unpaid": [dict(row, managers=[], reasons=["waiting_payment"])],
        },
        "payout_requests": [],
    }
    monkeypatch.setattr(
        AdminDashboardService,
        "get_worklist_attention_counts",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard_charts",
        AsyncMock(
            return_value={
                "dates": [],
                "registrations_creators": [],
                "registrations_advertisers": [],
                "orders": [],
                "turnover": [],
            }
        ),
    )
    monkeypatch.setattr(
        AdminDashboardService,
        "get_order_workspace_activity",
        AsyncMock(return_value=None),
    )
    client = _build_admin_client(
        monkeypatch,
        dashboard_payload=payload,
        creators=[],
        advertisers=[],
        orders=[],
        order_card=dict(row, status_label="active", bloggers_needed=10),
    )

    def bridge(route):
        request = route.request
        assert request.method == "GET"
        if not request.url.startswith(BASE + "/"):
            route.abort()
            return
        response = client.get(request.url, headers=dict(request.headers))
        route.fulfill(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )

    page.route("**/*", bridge)
    page.goto(BASE + "/admin/dashboard?period=7d")
    delayed = page.locator(".attention-queue--delayed")
    moderation = page.locator(".attention-queue--moderation")
    expect(delayed.locator(".order-manager")).to_have_count(1)
    expect(delayed.locator(".order-manager a")).to_have_count(1)
    expect(moderation.locator(".order-manager")).to_have_count(2)
    expect(
        moderation.get_by_role("link", name="Telegram @sh_renetta")
    ).to_have_count(1)
    expect(delayed).to_contain_text("Просрочено на 6,8 дн.")
    expect(delayed).to_contain_text("4 вручную")
    expect(delayed).to_contain_text("Передано контактов 6")
    expect(delayed).to_contain_text("Подобрано по плану 2 из 10")
    expect(delayed).to_contain_text("Осталось подобрать 8")
    expect(delayed.get_by_role("progressbar")).to_have_attribute(
        "aria-valuenow", "20"
    )
    expect(delayed.get_by_role("progressbar")).to_have_attribute(
        "aria-valuetext", "2 из 10"
    )
    expect(delayed.locator(".order-manager a")).to_have_attribute(
        "href",
        f"{BASE}/admin/users/{MANAGER_ID}?from_order={ORDER_ID}"
        "&return_to=%2Fadmin%2Fdashboard%3Fperiod%3D7d",
    )
    unpaid = page.locator(".attention-queue").filter(
        has_text="Давно без оплаты"
    )
    unpaid.locator("summary").click()
    expect(unpaid).to_contain_text("Менеджер не назначен")

    for width in (1440, 768, 375, 320):
        page.set_viewport_size({"width": width, "height": 1000})
        expect(moderation).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        if width == 1440:
            left, right = moderation.bounding_box(), delayed.bounding_box()
            assert left["y"] == right["y"]
            assert left["height"] == right["height"]
            if directory := os.environ.get("UMC_UI_SCREENSHOTS"):
                Path(directory).mkdir(parents=True, exist_ok=True)
                page.get_by_role("region", name="Требует внимания").screenshot(
                    path=str(Path(directory) / "dashboard-order-cards.png")
                )
        screenshot(page, f"dashboard-order-cards-{width}")

    delayed.locator(".attention-list__main > a").click()
    expect(page.get_by_role("link", name="← К дашборду")).to_have_attribute(
        "href", "/admin/dashboard?period=7d"
    )
    expect(page.locator(".order-detail__stats .order-manager a")).to_have_count(
        1
    )
