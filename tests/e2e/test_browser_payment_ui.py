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


@pytest.mark.parametrize("state", ["available", "paid", "telegram_pending"])
def test_public_browser_payment_page(page, state):
    token = str(uuid4())
    posts = []

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
    page.goto(f"{UMC}/miniapp/browser-payment.html#{token}")
    expect(
        page.get_by_role("link", name="Не получилось оплатить")
    ).to_have_attribute("href", "https://t.me/usemycontent")
    email = page.get_by_role("textbox", name="Email для чека")
    if state == "available":
        email.fill("buyer@example.test")
        page.get_by_role("button", name="Перейти к оплате").click()
        expect(page).to_have_url(PAYMENT_URL)
        assert posts[-1][1] == {"token": token, "email": "buyer@example.test"}
    else:
        text = (
            "Заказ уже оплачен."
            if state == "paid"
            else "Проверяем предыдущую попытку"
        )
        expect(page.get_by_role("status")).to_contain_text(text)
        expect(email).to_be_hidden()
        assert all(not path.endswith("/start") for path, _ in posts)
    assert posts[0][1] == {"token": token}
