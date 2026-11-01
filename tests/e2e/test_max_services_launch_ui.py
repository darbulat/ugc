"""MAX launch payload must open the requested services screen."""

from playwright.sync_api import expect

from tests.e2e.test_customer_workflows_ui import FullServiceCatalogNetwork
from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_selection_ui import SIGNED


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
