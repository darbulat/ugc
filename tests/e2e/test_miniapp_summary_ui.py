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
        order_id = self.summary["order_id"]
        if path == f"/miniapp/api/orders/{order_id}/campaign-summary":
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
    expect(page.locator("#summary-order")).to_have_text("UMC-22000000")
    assert ORDER not in page.locator("#screen-summary").inner_text()
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


@pytest.mark.browser_context_args(viewport={"width": 390, "height": 844})
def test_preview_customer_sees_contacts_in_summary_after_confirmation(page):
    order_id = "e0828ce4-f2c3-429e-afb1-f97e27fdb3b8"
    network = SummaryNetwork()
    network.order.update(order_id=order_id, financial_version=None, price=0)
    network.summary.update(
        order_id=order_id,
        source="invite_preview",
        total=2,
        states={"awaiting_contact": 2},
        contact_accepted=None,
        creator_contacts=[
            {"ordinal": ordinal, "instagram": None, "telegram": None}
            for ordinal in (1, 2)
        ],
    )
    errors = open_app(page, network, native=True, init_data=SIGNED)
    page.locator("#btn-show-orders-list").click()
    page.locator("#orders-list [data-summary-open]").click()
    expect(page.locator("#summary-order")).to_have_text("UMC-E0828CE4")
    contacts = page.get_by_role("region", name="Контакты креаторов")
    expect(contacts.get_by_text("Ожидает контакта")).to_have_count(2)
    expect(contacts.get_by_role("link")).to_have_count(0)
    network.summary["creator_contacts"][0].update(
        instagram="@umc_e0828ce4_demo", telegram="@umc_e0828ce4_demo"
    )
    network.summary["states"] = {"contact_received": 1, "awaiting_contact": 1}
    page.evaluate("window.__host.wa.MainButton.click()")
    first = contacts.get_by_role("listitem").filter(has_text="№1")
    instagram = first.get_by_role("link", name="Instagram")
    telegram = first.get_by_role("link", name="Telegram")
    expect(instagram).to_have_attribute(
        "href", "https://instagram.com/umc_e0828ce4_demo/"
    )
    expect(telegram).to_have_attribute("href", "https://t.me/umc_e0828ce4_demo")
    for contact in (instagram, telegram):
        expect(contact).to_contain_text("@umc_e0828ce4_demo")
        expect(contact).to_have_css("border-top-width", "1px")
        expect(contact).to_have_css("min-height", "56px")
    instagram.click()
    telegram.click()
    assert (
        page.evaluate("window.__host.calls").count(
            ["link", "https://instagram.com/umc_e0828ce4_demo/"]
        )
        == 1
    )
    assert (
        page.evaluate("window.__host.calls").count(
            ["telegram-link", "https://t.me/umc_e0828ce4_demo"]
        )
        == 1
    )
    expect(contacts.get_by_text("Ожидает контакта")).to_have_count(1)

    network.summary_code = 403
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#summary-error")).not_to_be_empty()
    expect(page.locator("#summary-creator-contacts-list")).to_be_empty()
    assert not errors


def test_contact_links_use_only_the_expected_social_domains(page):
    network = SummaryNetwork()
    network.summary["creator_contacts"] = [
        {
            "ordinal": 1,
            "instagram": "https://www.instagram.com/synthetic_creator",
            "telegram": "https://t.me/synthetic_creator",
        },
        {
            "ordinal": 2,
            "instagram": "https://instagram.com.example.test/invalid",
            "telegram": "javascript:alert(1)",
        },
    ]
    errors = open_app(
        page, network, init_data=SIGNED, query=f"?summary={ORDER}"
    )
    contacts = page.get_by_role("region", name="Контакты креаторов")
    expect(contacts.get_by_role("link")).to_have_count(2)
    expect(
        contacts.get_by_role("link", name="Instagram", exact=False)
    ).to_have_attribute("href", "https://instagram.com/synthetic_creator/")
    expect(
        contacts.get_by_role("link", name="Telegram", exact=False)
    ).to_have_attribute("href", "https://t.me/synthetic_creator")
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
        list_id, return_screen = "orders-list", "screen-customer-orders"
    else:
        page.locator("#btn-manager-role").click()
        list_id, return_screen = "manager-orders-list", "screen-manager-orders"
    page.locator(f"#{list_id} [data-summary-open]").click()
    expect(page.locator("#summary-total")).to_have_text("30")
    expect(page.locator("#summary-order")).to_have_text("UMC-22000000")
    assert ORDER not in page.locator("#screen-summary").inner_text()
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
