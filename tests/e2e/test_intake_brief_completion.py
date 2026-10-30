"""The actual paid form retains and submits the complete client brief."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED
from tests.e2e.test_miniapp_selection_ui import SelectionNetwork, fill

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_full_brief_restores_and_submits_without_losing_filters(page, platform):
    network = SelectionNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    for name, value in dict(
        city="Москва",
        content_usage="Вертикальное видео",
        brief_link="https://example.com/brief",
    ).items():
        page.locator("#intake-" + name).fill(value)
    page.locator("#intake-platform-youtube").check()
    page.locator("#intake-order-type").select_option("ugc_plus_placement")
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-city")).to_have_value("Москва")
    expect(page.locator("#intake-platform-youtube")).to_be_checked()
    expect(page.locator("#intake-order-type")).to_have_value(
        "ugc_plus_placement"
    )
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    payload = network.creates[0]
    assert payload["targeting"]["city"] == "Москва"
    assert payload["targeting"]["platforms"] == ["youtube"]
    assert payload["targeting"]["brief_link"] == "https://example.com/brief"
    assert payload["order_type"] == "ugc_plus_placement"
    assert not errors
