"""Interrupted registration keeps the verified account, profile and intent."""

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app
from tests.e2e.test_miniapp_selection_ui import SelectionNetwork
from tests.e2e.test_miniapp_social_ui import SIGNED_DATA, SocialNetwork

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.timeout(30),
    pytest.mark.parametrize("platform", ["telegram", "max"]),
]


@pytest.mark.parametrize(
    ("role", "prefix"), [("advertiser", "adv"), ("blogger", "blg")]
)
def test_resumed_agreement_cannot_confirm_another_account(
    page: Page, platform: str, role: str, prefix: str
) -> None:
    network = MiniAppNetwork(registered=role == "advertiser")
    network.advertiser_agreed = False
    network.blogger_registered = role == "blogger"
    network.blogger_agreement_confirmed = False
    errors = open_app(page, network, platform)
    expect(page.locator(f"#screen-agreements-{role}")).to_be_visible()
    page.locator(f"#{prefix}-agree-checkbox").check()
    page.evaluate("window.__host.wa.initData = 'different-account'")
    button = page.locator(f"#btn-confirm-{prefix}-agreement")
    button.click()
    expect(page.locator(f"#{prefix}-agreement-error")).not_to_be_empty()
    expect(button).to_be_enabled()
    assert not any(
        path.endswith("/confirm-agreement") for path, _ in network.requests
    )
    assert not errors


def test_resumed_agreement_prefills_the_latest_saved_profile(
    page: Page, platform: str
) -> None:
    network = MiniAppNetwork(registered=True)
    network.advertiser_agreed = False
    errors = open_app(page, network, platform)
    page.locator("#back-from-adv-agreements").click()
    page.locator("#adv-brand").fill("Updated brand")
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.locator("#back-from-adv-agreements").click()
    page.locator("#back-from-advertiser").click()
    page.locator('[data-role="advertiser"]').click()
    page.locator("#back-from-adv-agreements").click()
    expect(page.locator("#adv-brand")).to_have_value("Updated brand")
    assert not errors


def test_agreement_order_history_cannot_open_for_a_switched_account(
    page: Page, platform: str
) -> None:
    network = MiniAppNetwork(registered=True)
    network.advertiser_agreed = False
    open_app(page, network, platform)
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.evaluate("window.__host.wa.initData = 'different-account'")
    page.locator("#btn-agreement-orders").click()
    expect(page.locator("#adv-agreement-error")).not_to_be_empty()
    expect(page.locator("#screen-customer-orders")).to_be_hidden()
    assert not any(
        path == "/orders/list" and body["init_data"] == "different-account"
        for path, body in network.requests
    )


def test_pending_creator_can_read_orders_and_gets_social_prompt_after_consent(
    page: Page, platform: str
) -> None:
    network = SocialNetwork()
    network.blogger_agreement_confirmed = False
    network.creator_orders = [
        {
            "order_id": "existing-creator-order",
            "status": "active",
            "price": 1000,
        }
    ]
    errors = open_app(page, network, platform, init_data=SIGNED_DATA)
    expect(page.locator("#screen-agreements-blogger")).to_be_visible()
    page.locator("#btn-blogger-agreement-orders").click()
    expect(page.locator("#blogger-agreement-orders-list")).to_contain_text(
        "existing-creator-order"
    )
    expect(page.locator("#screen-blogger-dashboard")).to_be_hidden()
    assert not any(path == "/social/accounts" for path, _ in network.requests)
    page.locator("#blg-agree-checkbox").check()
    page.locator("#btn-confirm-blg-agreement").click()
    expect(page.locator("#screen-social-prompt")).to_be_visible()
    assert not errors


def test_order_intent_keeps_manager_option_during_consent(
    page: Page, platform: str
) -> None:
    network = SelectionNetwork()
    network.advertiser_agreed = False
    errors = open_app(page, network, platform, query="?view=order")
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.evaluate("window.UMCSelection.create({withManager: true})")
    expect(page.locator("#screen-intake")).to_be_hidden()
    page.locator("#adv-agree-checkbox").check()
    page.locator("#btn-confirm-adv-agreement").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    expect(
        page.locator('[name="intake-mode"][value="with_manager"]')
    ).to_be_checked()
    assert not errors


def test_reopening_creator_agreement_discards_unsaved_map_pin(
    page: Page, platform: str
) -> None:
    page.add_init_script("""
      window.L = {
        map() {
          return {
            setView() { return this; },
            on() { return this; },
            removeLayer(marker) { marker.element.remove(); }
          };
        },
        tileLayer() { return { addTo() {} }; },
        marker() {
          const element = document.createElement('span');
          element.dataset.testMapPin = '';
          return {
            element,
            addTo() {
              document.getElementById('blogger-city-map').append(element);
              return this;
            },
            setLatLng() {}
          };
        }
      };
    """)
    network = MiniAppNetwork()
    network.blogger_registered = True
    network.blogger_agreement_confirmed = False
    network.blogger_city = "Saved city"
    errors = open_app(page, network, platform)
    page.locator("#back-from-blg-agreements").click()
    page.locator("#btn-blogger-city-map").click()
    page.locator("#blg-city-search").fill("Draft city")
    page.locator("#btn-blogger-city-search").click()
    expect(page.locator("#blg-city")).to_have_value("Synthetic city")
    expect(page.locator("[data-test-map-pin]")).to_have_count(1)
    page.locator("#back-from-blogger").click()
    page.locator('[data-role="blogger"]').click()
    page.locator("#back-from-blg-agreements").click()
    expect(page.locator("#blg-city")).to_have_value("Saved city")
    expect(page.locator("#blg-lat")).to_have_value("")
    expect(page.locator("[data-test-map-pin]")).to_have_count(0)
    expect(page.locator("#blg-city-map-hint")).to_have_text(
        "Нажмите на карту или найдите город"
    )
    assert not errors


def test_creator_profile_waits_for_the_latest_city_lookup(
    page: Page, platform: str
) -> None:
    class Network(MiniAppNetwork):
        held: list[Route]

        def __init__(self):
            super().__init__()
            self.held = []

        def route(self, route: Route) -> None:
            if route.request.url.endswith("/geocode/forward"):
                self.held.append(route)
            else:
                super().route(route)

    network = Network()
    network.blogger_registered = True
    network.blogger_agreement_confirmed = False
    network.blogger_city = "Saved city"
    open_app(page, network, platform)
    page.locator("#back-from-blg-agreements").click()
    page.locator("#blg-name").fill("Creator")
    page.locator("#blg-instagram").fill("synthetic")
    page.locator("#blg-birth-day").select_option("1")
    page.locator("#blg-birth-month").select_option("1")
    page.locator("#blg-birth-year").select_option("1990")
    page.locator("#blg-topics").fill("beauty")
    page.locator("#blg-audience-geo").fill("Russia")
    page.locator("#blg-price").fill("1000")
    page.locator("#btn-blogger-city-map").click()
    page.locator("#blg-city-search").fill("New city")
    page.locator("#btn-blogger-city-search").click()
    page.locator("#btn-blogger-city-search").click()
    page.locator("#btn-submit-blogger").click()
    expect(page.locator("#blg-error")).to_have_text("Загрузка…")
    assert len(network.held) == 2
    network.held[0].fulfill(json={"city": "Old result", "lat": 1, "lon": 2})
    page.locator("#btn-submit-blogger").click()
    expect(page.locator("#blg-error")).to_have_text("Загрузка…")
    assert not any(path == "/register/blogger" for path, _ in network.requests)
    network.held[1].fulfill(json={"city": "New city", "lat": 3, "lon": 4})
    expect(page.locator("#blg-city")).to_have_value("New city")
    page.locator("#btn-submit-blogger").click()
    expect(page.locator("#screen-agreements-blogger")).to_be_visible()
    payload = next(
        body for path, body in network.requests if path == "/register/blogger"
    )
    assert (payload["city"], payload["lat"], payload["lon"]) == (
        "New city",
        3,
        4,
    )
