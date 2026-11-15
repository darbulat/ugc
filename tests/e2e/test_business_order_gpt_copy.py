"""The private preview copies the entire brief and keeps it as plain text."""

from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect

APP = Path(__file__).resolve().parents[2] / "src" / "ugc_bot" / "miniapp"
ORIGIN = "https://orders.example.test"


@pytest.mark.e2e
@pytest.mark.parametrize("clipboard_available", [True, False])
def test_copy_order_prompt_in_telegram_webview(page, clipboard_available):
    order_id = str(uuid4())
    expected = (
        "Напиши первое сообщение.\n\n"
        "<script>Пожелание из заявки</script>\n"
        + "Условия подробного брифа. "
        * 250
    )
    page.route(
        "https://telegram.org/js/telegram-web-app.js",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body=(
                "window.Telegram = {WebApp: {initData: 'signed', ready() {}}};"
            ),
        ),
    )

    def load(route):
        assert route.request.method == "POST"
        assert route.request.post_data_json == {
            "init_data": "signed",
            "order_id": order_id,
        }
        route.fulfill(json={"prompt": expected})

    page.route(f"{ORIGIN}/miniapp/api/orders/gpt-copy", load)
    page.route(
        f"{ORIGIN}/miniapp/order-gpt-copy.html?order={order_id}",
        lambda route: route.fulfill(path=APP / "order-gpt-copy.html"),
    )
    page.route(
        f"{ORIGIN}/miniapp/order-gpt-copy.js",
        lambda route: route.fulfill(
            path=APP / "order-gpt-copy.js",
            content_type="application/javascript",
        ),
    )
    if clipboard_available:
        page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=ORIGIN
        )
    else:
        page.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {value: undefined});
            document.execCommand = () => false;
            """
        )

    page.goto(f"{ORIGIN}/miniapp/order-gpt-copy.html?order={order_id}")
    expect(page.get_by_role("textbox")).to_have_value(expected)
    page.get_by_role("button", name="Скопировать для GPT").click()
    if clipboard_available:
        expect(page.get_by_role("status")).to_contain_text("Скопировано")
        assert page.evaluate("navigator.clipboard.readText()") == expected
    else:
        expect(page.get_by_role("status")).to_contain_text("Текст выделен")
        assert (
            page.locator("textarea").evaluate(
                "(e) => e.value.slice(e.selectionStart, e.selectionEnd)"
            )
            == expected
        )
