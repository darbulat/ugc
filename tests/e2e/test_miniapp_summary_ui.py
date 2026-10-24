"""Real summary screen; only the authenticated API boundary is synthetic."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_selection_ui import (
    CLIENT,
    ORDER,
    SIGNED,
    SelectionNetwork,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class SummaryNetwork(SelectionNetwork):
    def __init__(self, locale="ru"):
        super().__init__(locale)
        self.summary_code = 200
        self.manager_role = False
        self.summary = dict(
            order_id=ORDER,
            source="financial_positions",
            role="client",
            total=30,
            states={"assigned": 25, "unassigned": 5},
            contact_accepted=25,
            as_of="2026-10-23T12:00:00Z",
        )
        self.order = dict(
            order_id=ORDER,
            financial_version="synthetic-v1",
            status="active",
            price=1,
            currency_symbol="₽",
            product_link="https://example.test/p",
        )

    def route(self, route):
        path = urlparse(route.request.url).path
        if path == "/miniapp/api/me":
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                json={
                    "user_id": CLIENT,
                    "locale": self.locale,
                    "country": "ru",
                    "currency_symbol": "₽",
                    "has_advertiser_profile": not self.manager_role,
                    "has_blogger_profile": False,
                    "is_manager": self.manager_role,
                }
            )
            return
        if path == f"/miniapp/api/orders/{ORDER}/campaign-summary":
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                status=self.summary_code,
                json=(
                    self.summary
                    if self.summary_code == 200
                    else {"detail": "unavailable"}
                ),
            )
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_real_summary_deeplink_locales_and_signed_read(page, platform, locale):
    network = SummaryNetwork(locale)
    errors = open_app(
        page,
        network,
        platform,
        native=True,
        init_data=SIGNED,
        query=f"?summary={ORDER}",
    )
    expect(page.locator("#screen-summary")).to_be_visible()
    expect(page.locator("#summary-total")).to_have_text("30")
    expect(page.locator('[data-summary-state="assigned"] dd')).to_have_text(
        "25"
    )
    expect(page.locator("#summary-contacts")).to_contain_text("25")
    expect(page.locator("#summary-source")).not_to_contain_text(
        "financial_positions"
    )
    request = next(
        body
        for path, body in network.requests
        if path.endswith("/campaign-summary")
    )
    assert request == {"init_data": SIGNED, "platform": platform}
    assert not errors
    if locale == "ru":
        page.set_viewport_size({"width": 320, "height": 700})
        screenshot(page, f"summary-{platform}-320")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_legacy_summary_and_refresh_failure_do_not_keep_old_counts(
    page, platform
):
    network = SummaryNetwork()
    network.summary.update(
        source="legacy_feedback",
        total=2,
        states={"legacy_pending": 1, "legacy_ok": 1},
        contact_accepted=None,
    )
    errors = open_app(
        page, network, platform, init_data=SIGNED, query=f"?summary={ORDER}"
    )
    expect(page.locator("#summary-content")).to_be_visible()
    expect(page.locator("#summary-contacts")).to_be_hidden()
    expect(page.locator("#summary-source")).to_contain_text("отзывы")
    network.summary_code = 503
    page.locator("#btn-summary-refresh").click()
    expect(page.locator("#summary-error")).not_to_be_empty()
    expect(page.locator("#summary-content")).to_be_hidden()
    assert not errors


def test_summary_duplicate_deeplink_is_rejected_without_request(page):
    network = SummaryNetwork()
    open_app(
        page,
        network,
        init_data=SIGNED,
        query=f"?summary={ORDER}&summary={ORDER}",
    )
    expect(page.locator("#summary-error")).not_to_be_empty()
    assert not any(
        path.endswith("/campaign-summary") for path, _ in network.requests
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("role", ["client", "manager"])
def test_summary_actual_order_entry_and_native_back(page, platform, role):
    network = SummaryNetwork()
    network.manager_role = role == "manager"
    network.summary["role"] = role
    errors = open_app(page, network, platform, native=True, init_data=SIGNED)
    if role == "client":
        page.locator("#btn-show-orders-list").click()
        list_id, return_screen = "orders-list", "screen-advertiser-dashboard"
    else:
        page.locator("#btn-manager-role").click()
        list_id, return_screen = "manager-orders-list", "screen-manager-orders"
    page.locator(f"#{list_id} [data-summary-open]").click()
    expect(page.locator("#summary-total")).to_have_text("30")
    page.wait_for_function("window.__host.wa.BackButton.visible")
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator(f"#{return_screen}")).to_be_visible()
    assert "summary=" not in page.url
    assert not errors


def test_summary_empty_unknown_and_dark_320_layout(page):
    network = SummaryNetwork("kk")
    network.summary.update(total=0, states={}, contact_accepted=0)
    errors = open_app(
        page, network, init_data=SIGNED, query=f"?summary={ORDER}"
    )
    expect(page.locator("#summary-empty")).not_to_be_empty()
    network.summary.update(total=1, states={"future_state": 1})
    page.locator("#btn-summary-refresh").click()
    expect(page.locator("#summary-states dt")).to_have_text("Белгісіз")
    page.set_viewport_size({"width": 320, "height": 640})
    page.evaluate(
        "window.__host.wa.colorScheme='dark'; "
        "window.__host.events.themeChanged()"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, "summary-kk-dark-320")
    assert not errors
