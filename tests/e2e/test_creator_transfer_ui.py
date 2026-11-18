"""Customer sees every delivered author and can review supplemental work."""

from urllib.parse import urlparse
from uuid import UUID

import pytest
from playwright.sync_api import expect

from tests.e2e.test_customer_workflows_ui import CustomerNetwork
from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_selection_ui import ORDER, POLICY, SIGNED

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class TransferNetwork(CustomerNetwork):
    def __init__(self):
        super().__init__()
        self.feedback = None
        self.orders = [
            dict(
                order_id=ORDER,
                public_title="ReBody",
                status="closed",
                created_at="2026-11-18T10:00:00Z",
                financial_version=POLICY,
                bloggers_needed=10,
                payment_state="paid",
                progress=dict(
                    delivered=15, completed=10, assigned=10, total=10
                ),
            )
        ]

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith(f"/financial/orders/{ORDER}/selection"):
            route.fulfill(
                json=dict(
                    order_id=ORDER,
                    policy_version=POLICY,
                    positions=self.positions,
                    waitlist_count=5,
                    writes_paused=False,
                    requested_authors=10,
                    delivered_authors=[
                        dict(
                            creator_id=str(UUID(int=index)),
                            contact=dict(
                                name=f"Автор {index}",
                                instagram=f"https://instagram.com/synthetic_author_{index}/",
                                telegram=f"synthetic_author_{index}",
                            ),
                            source="selection"
                            if index <= 10
                            else "counteroffer",
                            requested_price=None if index <= 10 else 3500,
                            sent_at="2026-11-18T10:00:00Z",
                        )
                        for index in range(1, 16)
                    ],
                )
            )
            return
        if path.endswith("/customer/orders/ratings"):
            route.fulfill(
                json={
                    "authors": [
                        dict(
                            blogger_id=str(UUID(int=index)),
                            display_name=f"Автор {index}",
                            supplemental=index > 10,
                            feedback=self.feedback if index == 15 else None,
                            rating_eligible=index == 15
                            and self.feedback == "worked",
                            ratings=[],
                        )
                        for index in range(1, 16)
                    ]
                }
            )
            return
        if path.endswith("/customer/orders/creator-feedback"):
            self.feedback = route.request.post_data_json["feedback"]
            route.fulfill(json={"ok": True})
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_customer_keeps_all_fifteen_contacts_and_can_review_extra_author(
    page, platform
):
    page.set_viewport_size({"width": 390, "height": 844})
    network = TransferNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.evaluate("window.UMCCustomer.orders()")
    card = page.locator("#orders-list article")
    expect(
        card.get_by_text("Передано авторов: 15 из 10", exact=True)
    ).to_have_count(1)
    card.get_by_role("button", name="Открыть заказ", exact=True).click()
    section = page.locator("[data-creator-handoffs]")
    expect(
        section.get_by_role("heading", name="Передано авторов: 15 из 10")
    ).to_be_visible()
    screenshot(page, "manual-delivery-compact-" + platform)
    section.locator("summary").click()
    expect(section.locator("[data-delivered-creator]")).to_have_count(15)
    expect(
        section.locator('a[href="https://t.me/synthetic_author_1"]')
    ).to_be_visible()
    expect(
        section.locator('a[href="https://t.me/synthetic_author_15"]')
    ).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, "manual-delivery-fifteen-" + platform)
    section.get_by_role("button", name="Оценить авторов").click()
    author = page.locator("#screen-customer-ratings article").last
    expect(page.locator("#screen-customer-ratings article")).to_have_count(15)
    expect(author.get_by_role("button", name="Сохранить оценку")).to_have_count(
        0
    )
    author.get_by_label("Сохранить результат").select_option("worked")
    author.get_by_role("button", name="Сохранить результат").click()
    expect(
        author.get_by_role("button", name="Сохранить оценку")
    ).to_be_visible()
    author.get_by_role("button", name="Сохранить оценку").click()
    expect(author.get_by_text("Оценка сохранена")).to_be_visible()
    assert network.feedback == "worked"
