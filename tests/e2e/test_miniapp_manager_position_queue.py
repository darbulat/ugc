"""A manager sees and filters the stages for their current order."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_invite_handoff_ui import ORDER, InviteNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.browser_context_args(
    viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
)
def test_manager_filters_and_refreshes_the_order_queue(page):
    class Network(InviteNetwork):
        def route(self, route):
            path = urlparse(route.request.url).path
            if not path.endswith("/position-queue"):
                super().route(route)
                return
            payload = route.request.post_data_json
            self.requests.append((path, payload))
            rows = [
                (1, "waiting", "Ждём ответа"),
                (2, "manual", "Ручной подбор"),
                (3, "received", "Контакт получен"),
            ]
            route.fulfill(
                json={
                    "positions": [
                        {
                            "ordinal": n,
                            "stage": stage,
                            "label": label,
                            "preview": True,
                        }
                        for n, stage, label in rows
                        if payload["stage"] in ("all", stage)
                    ]
                }
            )

    network = Network()
    network.registered = False
    network.order["product_link"] = "https://example.test/brand"
    errors = open_app(page, network)
    page.get_by_role("button", name="Менеджер", exact=True).tap()
    order = page.locator(f'[data-order-id="{ORDER}"]')
    expect(order.get_by_role("button", name="Сводка по заказу")).to_be_visible()
    order.get_by_role("button", name="Открыть заказ").tap()
    expect(page.get_by_role("button", name="Добавить креатора")).to_be_visible()
    toggle = page.get_by_role("button", name="Очередь по позициям")
    toggle.tap()
    panel = page.locator("#mgr-position-queue")
    expect(panel.get_by_role("listitem")).to_have_count(3)
    expect(panel.get_by_text("№2 · Ручной подбор")).to_be_visible()
    panel.get_by_role("button", name="Ждём ответа", exact=True).click()
    expect(panel.get_by_role("listitem")).to_have_text("№1 · Ждём ответа")
    panel.get_by_role("button", name="Обновить очередь").click()
    expect(panel.get_by_role("listitem")).to_have_text("№1 · Ждём ответа")
    assert network.requests[-1][0].endswith(f"/{ORDER}/position-queue")
    assert network.requests[-1][1]["stage"] == "waiting"
    toggle.click()
    expect(panel).to_be_hidden()
    assert not errors
