"""Real admin templates, synthetic snapshots and no external writes."""

import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import screenshot
from ugc_bot.admin import app as admin_app
from ugc_bot.admin.order_creators import creator_workspace

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(45)]
ORDER_ID = str(UUID(int=900))
BASE = "http://workspace.test"


def snapshot():
    at = datetime(2026, 11, 18, 12, tzinfo=UTC)
    responses, history, candidates, refusals = [], [], [], []
    for i in range(1, 24):
        cid = UUID(int=i)
        name = f"Резерв {i}" if 16 <= i <= 21 else f"Автор {i}"
        contact = dict(
            name=name,
            instagram=f"https://instagram.com/synthetic_author_{i}/",
            telegram=f"synthetic_author_{i}",
            phone=f"Тестовый контакт {i}",
        )
        if i <= 10 or 16 <= i <= 21:
            responses.append(
                dict(
                    blogger_id=str(cid),
                    name=name,
                    instagram=contact["instagram"],
                    telegram=contact["telegram"],
                    in_offer=i <= 10,
                    accepted=True,
                    responded_at=at,
                )
            )
        if i <= 15:
            history.append(
                dict(
                    creator_id=cid,
                    contact=contact,
                    source="selection" if i <= 10 else "counteroffer",
                    requested_price=None if i <= 10 else 3500,
                    sent_at=at,
                    feedback=None,
                )
            )
        if 11 <= i <= 15 or 16 <= i <= 21:
            candidates.append(
                dict(
                    creator_id=cid,
                    name=name,
                    source="Новая цена" if i <= 15 else "Резерв",
                    price=3500 if i <= 15 else None,
                    state="sent" if i <= 15 else None,
                )
            )
        if 11 <= i <= 15 or i >= 22:
            refusals.append(
                dict(
                    creator_id=cid,
                    name=name,
                    price=3500 if i <= 15 else None,
                    reason="Низкая цена" if i <= 15 else "Нет времени",
                )
            )
    card = dict(
        order_id=ORDER_ID,
        advertiser_id=str(UUID(int=901)),
        advertiser="Елизавета · пример",
        lifecycle_status="closed",
        financial_selection=True,
        status_label="Закрыт",
        offer_text="ReBody · пример карточки заказа",
        geography="Россия",
        order_type="ugc_only",
        price=1000,
        currency="RUB",
        bloggers_needed=10,
        picked_count=10,
        progress=1,
        created_at=at,
        updated_at=at,
        completed_at=at,
        manual_creator_count=0,
        managers=[],
        has_problem=False,
        brief_link="https://example.test/brief",
        product_link="https://example.test/product",
        product_photo_file_id="synthetic-photo",
        responses_list=responses,
        can_edit_closure_reason=False,
        closure_reason="",
        required_blogger_gender=None,
    )
    activity = dict(
        sent=42,
        targeted=50,
        failed=8,
        accepted=16,
        declined=7,
        via_invite=0,
        dispatch_status="Рассылка завершена",
        reasons={"Низкая цена": 5, "Нет времени": 2},
        refused=refusals,
        currency="RUB",
    )
    transfers = dict(
        count=15,
        needed=10,
        can_send=True,
        candidates=candidates,
        history=history,
    )
    return card, activity, transfers


def open_workspace(page, monkeypatch, *, payment_state="paid"):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("USE_REDIS_STORAGE", "false")
    card, activity, transfers = snapshot()

    async def get_card(self, order_id):
        return deepcopy(card)

    async def get_activity(self, order_id, **kwargs):
        return dict(
            activity=deepcopy(activity),
            transfers=deepcopy(transfers),
            workspace=creator_workspace(
                card["responses_list"], activity, transfers, offer_price=1000
            ),
        )

    monkeypatch.setattr(
        admin_app.AdminDashboardService, "get_order_card", get_card
    )
    monkeypatch.setattr(
        admin_app.AdminDashboardService,
        "get_order_workspace_activity",
        get_activity,
    )
    app = admin_app.create_admin_app()

    async def payment_view(order_id):
        return SimpleNamespace(
            state=payment_state,
            url="https://example.test/payment"
            if payment_state == "pending"
            else None,
            telegram_disabled=payment_state == "pending",
        )

    app.state.browser_checkout = SimpleNamespace(
        view=payment_view, can_create=True
    )
    client = TestClient(app, base_url=BASE)
    client.post(
        "/admin/login",
        data={"username": "test_admin", "password": "test_pass"},
        follow_redirects=False,
    )
    requests = []

    def bridge(route):
        request = route.request
        if not request.url.startswith(BASE + "/"):
            route.abort()
            return
        assert request.method == "GET", (
            "This browser audit must never send or pay"
        )
        requests.append(urlsplit(request.url).path)
        response = client.get(request.url, follow_redirects=False)
        route.fulfill(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )

    page.route("**/*", bridge)
    page.goto(f"{BASE}/admin/orders/{ORDER_ID}")
    expect(page.locator("#order-transferred-value")).to_have_text("15")
    return activity, requests, transfers


def test_one_creator_table_preserves_filters_and_contacts_during_refresh(
    page, monkeypatch
):
    page.clock.install()
    page.set_viewport_size({"width": 1440, "height": 900})
    activity, requests, transfers = open_workspace(page, monkeypatch)
    expect(page.get_by_role("table")).to_have_count(1)
    expect(page.locator("[data-creator-row]")).to_have_count(23)
    expect(page.locator("#browser-payment")).to_have_count(0)
    expect(page.locator(".order-detail__badges")).to_contain_text("Оплачен")
    expect(page.locator("#order-transferred-extra")).to_have_text(
        "+5 сверх плана"
    )
    assert (
        page.locator("#order-transferred-value").evaluate(
            "el => getComputedStyle(el).color"
        )
        == "rgb(180, 35, 50)"
    )
    assert (
        page.locator(".order-detail__transfer-line strong").evaluate(
            "el => el.getBoundingClientRect().height"
        )
        < 30
    )
    screenshot(page, "order-workspace-desktop")
    if directory := os.environ.get("UMC_UI_SCREENSHOTS"):
        page.locator(".order-detail__overview").screenshot(
            path=str(Path(directory) / "order-workspace-overview.png")
        )

    page.locator('[data-creator-filter="reserve"]').click()
    expect(page.locator("[data-creator-row]:visible")).to_have_count(6)
    expect(
        page.get_by_role("button", name="Отправить заказчице", exact=True)
    ).to_have_count(6)
    search = page.get_by_label("Найти креатора")
    search.fill("Резерв 16")
    expect(page.locator("[data-creator-row]:visible")).to_have_count(1)
    detail = page.locator(
        '[data-creator-detail="00000000-0000-0000-0000-000000000010"]'
    )
    detail.locator("summary").click()
    search.focus()
    activity["dispatch_status"] = "Рассылка завершена · данные сверены"
    contact = dict(
        name="Резерв 17",
        instagram="https://instagram.com/synthetic_author_17/",
        telegram="synthetic_author_17",
        phone="Тестовый контакт 17",
    )
    transfers["history"].append(
        dict(
            creator_id=UUID(int=17),
            contact=contact,
            source="reserve",
            sent_at=datetime(2026, 11, 18, 14, tzinfo=UTC),
            requested_price=1000,
            feedback=None,
        )
    )
    transfers["count"] = 16
    with page.expect_response(
        lambda response: urlsplit(response.url).path.endswith("/offer-activity")
    ):
        page.clock.fast_forward(20_000)
    expect(search).to_have_value("Резерв 16")
    expect(search).to_be_focused()
    expect(detail).to_have_attribute("open", "")
    expect(page.locator('[data-creator-filter="reserve"]')).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(page.locator("[data-creator-row]:visible")).to_have_count(1)
    expect(page.locator("#order-transferred-value")).to_have_text("16")
    expect(page.locator("#order-transferred-extra")).to_have_text(
        "+6 сверх плана"
    )
    search.fill("")
    page.locator('[data-creator-filter="delivered"]').click()
    expect(page.locator("[data-creator-row]:visible")).to_have_count(16)
    row = page.locator(
        '[data-creator-row="00000000-0000-0000-0000-000000000001"]'
    )
    row.locator("summary").click()
    expect(row).to_contain_text("Тестовый контакт 1")
    assert all("send-to-customer" not in path for path in requests)

    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator('[data-creator-filter="reserve"]').click()
    screenshot(page, "order-workspace-mobile")


@pytest.mark.parametrize(
    "state, text",
    [
        ("pending", "Ожидает подтверждения от ЮKassa."),
        ("review", "Платёж сверяется."),
        ("telegram_pending", "Проверяем предыдущую попытку оплаты в Telegram."),
    ],
)
def test_unfinished_payment_remains_actionable(page, monkeypatch, state, text):
    open_workspace(page, monkeypatch, payment_state=state)
    expect(page.locator("#browser-payment")).to_contain_text(text)
    if state == "pending":
        expect(page.get_by_label("Ссылка для клиента")).to_have_value(
            "https://example.test/payment"
        )
        expect(
            page.get_by_role("button", name="Скопировать ссылку", exact=True)
        ).to_be_visible()
