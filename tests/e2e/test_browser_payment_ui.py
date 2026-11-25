"""The buyer enters the receipt email on a regular browser payment page."""

from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ASSETS = Path(__file__).resolve().parents[2] / "src" / "ugc_bot" / "miniapp"
UMC = "https://bot.example.test"
PAYMENT_URL = "https://yookassa.ru/my/i/test/a"


@pytest.mark.parametrize(
    "state, consultation",
    [
        ("available", False),
        ("paid", False),
        ("telegram_pending", False),
        ("available", True),
        ("paid", True),
    ],
)
def test_public_browser_payment_page(page, state, consultation):
    token = str(uuid4())
    posts = []
    service = {"service": "consultation"} if consultation else {}

    def response(route):
        path = urlsplit(route.request.url).path
        if route.request.url == PAYMENT_URL:
            return route.fulfill(body="YooKassa hosted checkout")
        if path.endswith(("/status", "/start")):
            payload = route.request.post_data_json
            posts.append((path, payload))
            assert payload["token"] == token
            assert token not in route.request.url
            return route.fulfill(
                json={"state": "pending", "url": PAYMENT_URL}
                if path.endswith("/start")
                else {"state": state}
            )
        name = Path(path).name
        return route.fulfill(
            content_type="text/html"
            if name.endswith(".html")
            else "application/javascript",
            body=(ASSETS / name).read_text(),
        )

    page.route("**/*", response)
    query = "?service=consultation" if consultation else ""
    page.goto(f"{UMC}/miniapp/browser-payment.html{query}#{token}")
    if consultation:
        expect(page.get_by_role("heading")).to_have_text(
            "Консультация по запуску UGC · 5 000 ₽"
        )
    expect(
        page.get_by_role("link", name="Не получилось оплатить")
    ).to_have_attribute("href", "https://t.me/usemycontent")
    email = page.get_by_role("textbox", name="Email для чека")
    if state == "available":
        email.fill("buyer@example.test")
        page.get_by_role("button", name="Перейти к оплате").click()
        expect(page).to_have_url(PAYMENT_URL)
        assert posts[-1][1] == {
            "token": token,
            "email": "buyer@example.test",
            **service,
        }
    else:
        text = (
            "Заказ уже оплачен."
            if state == "paid"
            else "Проверяем предыдущую попытку"
        )
        if consultation:
            text = "Консультация оплачена."
        expect(page.get_by_role("status")).to_contain_text(text)
        expect(email).to_be_hidden()
        assert all(not path.endswith("/start") for path, _ in posts)
    assert posts[0][1] == {"token": token, **service}


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("selected", [False, True])
def test_optional_consultation_in_miniapp_quote(page, platform, selected):
    from tests.e2e.test_miniapp_design_system import open_app
    from tests.e2e.test_miniapp_selection_ui import (
        SIGNED,
        SelectionNetwork,
        fill,
    )

    checkout_url = (
        f"{UMC}/miniapp/browser-payment.html?service=consultation#{uuid4()}"
    )

    class ConsultationNetwork(SelectionNetwork):
        def route(self, route):
            if (
                urlsplit(route.request.url).path
                == "/miniapp/api/financial/orders/policies"
            ):
                return route.fulfill(
                    json={
                        "policies": self.policies,
                        "consultation_minor": 500000,
                    }
                )
            return super().route(route)

        def created(self, payload):
            result = super().created(payload)
            amount = 500000 if payload.get("consultation_requested") else 0
            return result | {
                "consultation_minor": amount,
                "project_total_minor": result["total_minor"] + amount,
                "consultation_url": checkout_url if amount else None,
            }

    network = ConsultationNetwork()
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=order"
    )
    form = page.locator("#form-umc-intake")
    expect(form).to_be_visible()
    fill(page, manager=True)
    page.locator("#intake-count").fill("10")
    page.locator("#intake-all-manager").check()
    extra = form.get_by_role("checkbox", name="Разбор запуска UGC")
    expect(extra).not_to_be_checked()
    expect(page.locator("#intake-preview")).to_contain_text("17\u00a0000,00")
    extra.check()
    expect(page.locator("#intake-preview")).to_contain_text("22\u00a0000,00")
    if not selected:
        extra.uncheck()
        expect(page.locator("#intake-preview")).to_contain_text(
            "17\u00a0000,00"
        )
    page.locator("#btn-intake-create").click()
    saved = page.locator("#intake-result")
    expect(saved).to_be_visible()
    assert network.creates[0].get("consultation_requested", False) is selected
    expect(saved.locator("#intake-total")).to_have_attribute(
        "data-minor", "2200000" if selected else "1700000"
    )
    payment = saved.get_by_role("link", name="Оплатить консультацию")
    if selected:
        expect(payment).to_have_attribute("href", checkout_url)
        expect(saved).to_contain_text("оплачиваются отдельными платежами")
    else:
        expect(payment).to_have_count(0)
    assert not errors
