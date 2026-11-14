"""Local browser regressions for existing Mini App workflows and host controls.

Only the network boundary is synthetic. Production templates, assets, validation
and navigation run unchanged in Chromium. No live users or payments are used.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Route, expect

MINIAPP = Path(__file__).resolve().parents[2] / "src/ugc_bot/miniapp"
pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class MiniAppNetwork:
    def __init__(self, locale: str = "ru", registered: bool = False) -> None:
        self.locale = locale
        self.registered = registered
        self.requests: list[tuple[str, dict]] = []
        self.failure = False
        self.blogger_registered = False
        self.manager = False
        self.order: dict = {}
        self.symbol = {"ru": "₽", "en": "$", "kk": "₸"}[locale]

    def route(self, route: Route) -> None:  # noqa: PLR0912
        url = urlparse(route.request.url)
        if url.path.startswith("/miniapp/api/"):
            path = url.path.removeprefix("/miniapp/api")
            body = route.request.post_data_json
            self.requests.append((path, body))
            if path == "/me":
                data = {
                    "locale": self.locale,
                    "country": {"ru": "ru", "en": "ge", "kk": "kz"}[
                        self.locale
                    ],
                    "currency_symbol": self.symbol,
                    "has_advertiser_profile": self.registered,
                    "has_blogger_profile": self.blogger_registered,
                    "blogger_profile": {"confirmed": False}
                    if self.blogger_registered
                    else None,
                    "is_manager": self.manager,
                }
            elif path == "/config":
                data = {
                    "allowed_blogger_counts": [1, 5],
                    "content_usage_options": [],
                    "docs_offer_url": "https://example.test/offer",
                    "docs_privacy_url": "https://example.test/privacy",
                }
            elif path == "/register/advertiser":
                if self.failure:
                    route.fulfill(
                        status=422,
                        json={"detail": "Synthetic validation error"},
                    )
                    return
                data = {"needs_agreement": True}
            elif path == "/register/advertiser/confirm-agreement":
                self.registered = True
                data = {"ok": True}
            elif path == "/register/blogger":
                data = {"needs_agreement": True}
            elif path == "/register/blogger/confirm-agreement":
                self.blogger_registered = True
                data = {"ok": True}
            elif path == "/geocode/forward":
                data = {
                    "city": "Synthetic city",
                    "region": "Synthetic region",
                    "country": "Synthetic country",
                    "lat": 0,
                    "lon": 0,
                }
            elif path == "/orders/list/creator":
                data = {"orders": []}
            elif path == "/manager/orders":
                data = {
                    "orders": [self.order] if self.order else [],
                    "total": 1 if self.order else 0,
                }
            elif path.endswith("/creators"):
                data = {
                    "creators": [
                        {
                            "blogger_id": "synthetic-creator",
                            "name": "Synthetic creator",
                            "desired_price": "17000",
                        }
                    ]
                    if body.get("filter") == "expensive"
                    else [],
                    "total": 1 if body.get("filter") == "expensive" else 0,
                }
            elif path == "/orders":
                self.order = {
                    **body,
                    "order_id": "synthetic-order-1",
                    "status": "draft",
                    "currency_symbol": self.symbol,
                }
                data = {"order_id": self.order["order_id"]}
            elif path == "/orders/list":
                data = {"orders": [self.order] if self.order else []}
            elif path == "/orders/get":
                data = self.order
            else:
                route.fulfill(
                    status=404, json={"detail": f"Unexpected test API: {path}"}
                )
                return
            route.fulfill(json=data)
            return
        if url.hostname != "miniapp.test":
            route.fulfill(body="", content_type="application/javascript")
            return
        relative = url.path.removeprefix("/miniapp/")
        asset = MINIAPP / relative
        if asset.is_file() and asset.is_relative_to(MINIAPP):
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404, body="Missing local asset")


def open_app(
    page: Page,
    network: MiniAppNetwork,
    platform: str = "telegram",
    *,
    native: bool = False,
    host: bool = True,
    init_data: str = "synthetic-test-auth",
    query: str = "",
) -> list[str]:
    page.set_default_timeout(8_000)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/*", network.route)
    if host:
        script = Path(__file__).with_name("miniapp_host_mock.js").read_text()
        script = script.replace("__PLATFORM__", json.dumps(platform))
        script = script.replace("__NATIVE__", json.dumps(native))
        script = script.replace("__INIT_DATA__", json.dumps(init_data))
        page.add_init_script(script=script)
    template = "max_app.html" if platform == "max" else "app.html"
    page.goto(f"http://miniapp.test/miniapp/{template}{query}")
    return errors


def screenshot(page: Page, name: str) -> None:
    directory = os.environ.get("UMC_UI_SCREENSHOTS")
    if directory:
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(output / f"{name}.png"),
            full_page=True,
            animations="disabled",
        )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk"])
def test_local_registration_and_order_workflow(
    page: Page, platform: str, locale: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    from tests.e2e.test_miniapp_selection_ui import SelectionNetwork, fill

    network = SelectionNetwork(locale)
    network.registered = False
    errors = open_app(page, network, platform)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    expect(page.locator("html")).to_have_attribute("lang", locale)
    screenshot(page, f"{platform}-{locale}-roles-light")
    page.locator('[data-role="advertiser"]').click()
    expect(page.locator("#screen-register-advertiser")).to_be_visible()
    page.locator("#adv-name").fill("Synthetic UI account")
    page.locator("#adv-phone").fill("89001234567")
    page.locator("#adv-brand").fill("Synthetic test brand")
    screenshot(page, f"{platform}-{locale}-registration-light")
    page.locator("#btn-submit-advertiser").click()
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.locator("#adv-agree-checkbox").check()
    page.locator("#btn-confirm-adv-agreement").click()
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    page.locator("#btn-show-orders-list").click()
    expect(page.locator("#screen-customer-orders")).to_be_visible()
    expect(page.locator("#screen-customer-orders article")).to_have_count(0)
    page.locator("#screen-customer-orders button").nth(1).click()
    expect(page.locator("#screen-intake")).to_be_visible()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0]["position_count"] == 30
    assert network.creates[0]["platform"] == platform
    page.locator("#btn-intake-selection").click()
    expect(page.locator("#screen-selection")).to_be_visible()
    assert not errors
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, f"{platform}-{locale}-orders-light")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_submit_back_validation_and_theme(
    page: Page, platform: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    network = MiniAppNetwork()
    errors = open_app(page, network, platform, native=True)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.locator('[data-role="advertiser"]').click()
    expect(page.locator("#btn-submit-advertiser")).to_be_hidden()
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#adv-phone")).to_have_attribute("aria-invalid", "true")
    assert not any(
        path == "/register/advertiser" for path, _ in network.requests
    )
    page.locator("#adv-phone").fill("89001234567")
    page.locator("#adv-brand").fill("Synthetic native form")
    network.failure = True
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#adv-error")).to_have_text(
        "Synthetic validation error"
    )
    expect(page.locator("#form-advertiser")).to_have_attribute(
        "aria-busy", "false"
    )
    network.failure = False
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    # The native action keeps the real agreement checkbox validation.
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#adv-agreement-error")).not_to_be_empty()
    page.locator("#adv-agree-checkbox").check()
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    page.locator("#btn-adv-update-profile").click()
    expect(page.locator("#back-from-advertiser")).to_be_hidden()
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.evaluate(
        "window.__host.wa.colorScheme = 'dark'; "
        "window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert (
        page.evaluate("getComputedStyle(document.body).color")
        == "rgb(242, 242, 243)"
    )
    assert (
        page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--umc-safe-bottom').trim()"
        )
        == "20px"
    )
    assert page.evaluate(
        "window.__host.calls.some(x => x[0] === 'background' "
        "&& x[1] === '#121214')"
    )
    screenshot(page, f"{platform}-native-dark")
    page.locator('[data-role="blogger"]').click()
    expect(page.locator("#screen-register-blogger")).to_be_visible()
    screenshot(page, f"{platform}-native-creator-dark")
    assert not errors


def test_hostless_browser_theme_and_auth_fallback(page: Page) -> None:
    page.set_viewport_size({"width": 320, "height": 640})
    page.emulate_media(color_scheme="dark", reduced_motion="reduce")
    errors = open_app(page, MiniAppNetwork(), host=False)
    expect(page.locator("html")).to_have_attribute("data-host", "browser")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator("#screen-loading")).to_contain_text("Telegram")
    expect(page.locator("#screen-loading")).to_have_attribute(
        "aria-busy", "false"
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, "browser-auth-dark-320")
    assert not errors


def test_pending_native_action_and_capability_failure_keep_real_form(
    page: Page,
) -> None:
    network = MiniAppNetwork()
    errors = open_app(page, network, native=True)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.locator('[data-role="advertiser"]').click()
    expect(page.locator("#btn-submit-advertiser")).to_be_hidden()
    pending: list[Route] = []
    page.route(
        "**/miniapp/api/register/advertiser",
        lambda route: pending.append(route),
    )
    page.locator("#adv-phone").fill("89001234567")
    page.locator("#adv-brand").fill("Synthetic pending form")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#form-advertiser")).to_have_attribute(
        "aria-busy", "true"
    )
    assert (
        page.evaluate("window.__host.wa.MainButton.params.is_active") is False
    )
    assert page.evaluate("window.__host.wa.MainButton.busy") is True
    assert len(pending) == 1
    pending.pop().fulfill(
        status=422, json={"detail": "Synthetic retryable failure"}
    )
    expect(page.locator("#adv-error")).to_have_text(
        "Synthetic retryable failure"
    )
    expect(page.locator("#form-advertiser")).to_have_attribute(
        "aria-busy", "false"
    )
    # A rejected host capability restores the in-page action.
    page.evaluate("""() => {
      window.__host.wa.MainButton.setParams = () => {
        throw new Error('Unsupported host');
      };
      window.__host.wa.colorScheme = 'dark';
      window.__host.events.themeChanged();
    }""")
    expect(page.locator("#btn-submit-advertiser")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 500})
    expect(page.locator("html")).to_have_attribute("data-keyboard", "open")
    assert not errors


def test_desktop_layout_and_local_font_assets(page: Page) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    errors = open_app(page, MiniAppNetwork(registered=True))
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    page.evaluate("document.fonts.ready")
    assert page.locator("#umc-app").bounding_box()["width"] == 680
    assert (
        page.evaluate("document.querySelector('.umc-brand img').naturalWidth")
        > 0
    )
    assert any(
        "/miniapp/design-system/fonts/" in url and url.endswith("woff2")
        for url in requests
    )
    assert not any(
        "fonts.googleapis" in url or "fonts.gstatic" in url for url in requests
    )
    screenshot(page, "desktop-advertiser-light")
    assert not errors


def test_native_click_after_screen_transition_uses_current_action(
    page: Page,
) -> None:
    errors = open_app(page, MiniAppNetwork(), native=True)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.locator('[data-role="advertiser"]').click()
    expect(page.locator("#btn-submit-advertiser")).to_be_hidden()
    page.locator("#adv-phone").fill("89001234567")
    page.locator("#adv-brand").fill("Synthetic fast native flow")
    # Freeze rendering to expose a host click before the next repaint.
    page.evaluate("window.requestAnimationFrame = () => 0")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#screen-agreements-advertiser")).to_be_visible()
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#adv-agreement-error")).not_to_be_empty()
    assert not errors


@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_creator_registration_city_search_and_empty_orders(
    page: Page, locale: str
) -> None:
    page.set_viewport_size({"width": 320, "height": 640})
    network = MiniAppNetwork(locale)
    errors = open_app(page, network)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.locator('[data-role="blogger"]').click()
    page.locator("#blg-name").fill("Synthetic creator")
    page.locator("#blg-instagram").fill("synthetic_creator")
    page.locator("#blg-birth-year").select_option("1995")
    page.locator("#blg-topics").fill("beauty, fashion")
    page.locator("#blg-audience-geo").fill("Synthetic country")
    page.locator("#blg-price").fill("10000")
    page.locator("#btn-blogger-city-map").click()
    page.locator("#blg-city-search").fill("Synthetic city")
    page.locator("#blg-city-search").press("Enter")
    expect(page.locator("#blg-city")).to_have_value("Synthetic city")
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    page.locator("#btn-blogger-city-map").click()
    screenshot(page, f"telegram-{locale}-creator-form-320")
    page.locator("#btn-submit-blogger").click()
    expect(page.locator("#screen-agreements-blogger")).to_be_visible()
    page.locator("#blg-agree-checkbox").check()
    page.locator("#btn-confirm-blg-agreement").click()
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#blogger-instagram-warning")).to_be_visible()
    page.locator("#btn-blogger-orders").click()
    expect(page.locator("#blogger-orders-list li")).to_have_count(1)
    assert page.locator("#blogger-orders-list").inner_text().strip()
    created = next(
        body for path, body in network.requests if path == "/register/blogger"
    )
    assert created["instagram_url"] == "https://instagram.com/synthetic_creator"
    assert created["city"] == "Synthetic city" and created["price"] == 10000
    screenshot(page, f"telegram-{locale}-creator-dashboard-320")
    assert not errors


def test_manager_navigation_preserves_order_currency(page: Page) -> None:
    network = MiniAppNetwork("kk")
    network.manager = True
    network.order = {
        "order_id": "synthetic-order-1",
        "product_link": "https://example.test/synthetic-product",
        "status": "draft",
        "price": "9007199254740993",
        "currency_symbol": "$",
    }
    errors = open_app(page, network)
    expect(page.locator("#screen-role-choice")).to_be_visible()
    page.locator('[data-role="manager"]').click()
    row = page.locator("#manager-orders-list li").first
    expect(row).to_contain_text("9007199254740993")
    expect(row).to_have_attribute("role", "button")
    row.focus()
    row.press("Space")
    expect(page.locator("#screen-manager-order-detail")).to_be_visible()
    page.locator("#btn-mgr-creators-expensive").click()
    expect(page.locator("#manager-creators-list")).to_contain_text("$")
    assert "₽" not in page.locator("#manager-creators-list").inner_text()
    assert "₸" not in page.locator("#manager-creators-list").inner_text()
    screenshot(page, "manager-kazakh-expensive-order-currency")
    assert not errors


def test_native_payment_mirrors_existing_link_without_simulating_success(
    page: Page,
) -> None:
    network = MiniAppNetwork(registered=True)
    network.order = {
        "order_id": "synthetic-order-1",
        "product_link": "https://example.test/synthetic-product",
        "offer_text": "Synthetic payment navigation",
        "status": "draft",
        "price": "15000",
        "currency_symbol": "₽",
        "payment_link": "https://payments.example.test/synthetic-checkout",
    }
    errors = open_app(page, network, native=True)
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    page.locator("#btn-show-orders-list").click()
    page.locator("#screen-customer-orders article button").first.click()
    expect(page.locator("#screen-order-detail")).to_be_visible()
    expect(page.locator("#btn-order-detail-pay")).to_be_hidden()
    page.evaluate("window.__host.wa.MainButton.click()")
    assert page.evaluate(
        "window.__host.calls.filter(x => x[0] === 'link')"
    ) == [["link", network.order["payment_link"]]]
    assert page.evaluate(
        "window.__host.calls.filter(x => x[0] === 'close')"
    ) == [["close"]]
    assert not errors
