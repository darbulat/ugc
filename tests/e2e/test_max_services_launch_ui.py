"""MAX launch payload must open the requested services screen."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_customer_workflows_ui import FullServiceCatalogNetwork
from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_selection_ui import SIGNED

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def test_max_launch_payload_opens_services(page):
    errors = open_app(
        page,
        FullServiceCatalogNetwork(),
        "max",
        init_data=SIGNED + "&start_param=services",
    )
    expect(page.locator("#screen-customer-services")).to_be_visible()
    expect(page.locator("#screen-customer-services article")).to_have_count(5)
    assert not errors


@pytest.mark.parametrize(
    ("creator", "expected"),
    [(False, "screen-role-choice"), (True, "screen-blogger-dashboard")],
)
def test_max_services_back_returns_to_actual_home(page, creator, expected):
    class Network(FullServiceCatalogNetwork):
        def route(self, route):
            if route.request.url.endswith("/miniapp/api/me"):
                route.fulfill(
                    json={
                        "user_id": "synthetic",
                        "locale": "ru",
                        "country": "ru",
                        "currency_symbol": "₽",
                        "has_advertiser_profile": False,
                        "has_blogger_profile": creator,
                        "blogger_profile": {"confirmed": True}
                        if creator
                        else None,
                        "is_manager": False,
                    }
                )
            else:
                super().route(route)

    errors = open_app(
        page, Network(), "max", init_data=SIGNED + "&start_param=services"
    )
    services = page.locator("#screen-customer-services")
    expect(services).to_be_visible()
    services.locator("[data-umc-back]").first.click()
    expect(page.locator("#" + expected)).to_be_visible()
    assert not errors
