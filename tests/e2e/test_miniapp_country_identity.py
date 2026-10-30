"""Country selection must stay bound to the account that loaded it."""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import (
    MINIAPP,
    MiniAppNetwork,
    open_app,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
FIRST = "synthetic-first-account"
SECOND = "synthetic-second-account"


class CountryNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.countries = {}
        self.hold_country = False
        self.held_country = []
        self.hold_module = False
        self.held_module = []
        self.hold_me = False
        self.held_me = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if self.hold_module and path == "/miniapp/umc-shell.js":
            self.held_module.append(route)
            return
        if path in (
            "/miniapp/api/me",
            "/miniapp/api/config",
            "/miniapp/api/set-country",
        ):
            body = route.request.post_data_json
            api_path = path.removeprefix("/miniapp/api")
            self.requests.append((api_path, body))
            if api_path == "/me":
                if self.hold_me:
                    self.held_me.append((route, body))
                    return
                route.fulfill(
                    json={
                        "user_id": body["init_data"],
                        "country": self.countries.get(body["init_data"]),
                        "locale": "ru",
                        "currency_symbol": "₽",
                        "has_advertiser_profile": False,
                        "has_blogger_profile": False,
                        "is_manager": False,
                    }
                )
            elif api_path == "/config":
                route.fulfill(
                    json={
                        "countries": [{"code": "ru", "name_native": "Россия"}]
                    }
                )
            elif self.hold_country:
                self.held_country.append((route, body))
            else:
                self.countries[body["init_data"]] = body["country_code"]
                route.fulfill(json={"ok": True})
            return
        super().route(route)


def test_country_selection_succeeds_for_the_loaded_account(page):
    network = CountryNetwork()
    open_app(page, network, init_data=FIRST)
    page.get_by_role("button", name="Россия").click()
    expect(page.locator("#screen-role-choice")).to_be_visible()
    assert network.countries == {FIRST: "ru"}


def test_switched_account_cannot_set_country_from_another_accounts_screen(page):
    network = CountryNetwork()
    open_app(page, network, init_data=FIRST)
    expect(page.locator("#screen-country-select")).to_be_visible()
    page.evaluate("auth => { window.__host.wa.initData = auth; }", SECOND)
    page.get_by_role("button", name="Россия").click()
    expect(page.locator("#country-error")).not_to_be_empty()
    assert not [path for path, _ in network.requests if path == "/set-country"]
    assert network.countries == {}


def test_switch_while_setting_country_does_not_load_a_different_account(page):
    network = CountryNetwork()
    network.hold_country = True
    open_app(page, network, init_data=FIRST)
    page.get_by_role("button", name="Россия").click()
    assert len(network.held_country) == 1
    route, body = network.held_country.pop()
    page.evaluate("auth => { window.__host.wa.initData = auth; }", SECOND)
    network.countries[body["init_data"]] = body["country_code"]
    route.fulfill(json={"ok": True})
    expect(page.locator("#country-error")).not_to_be_empty()
    assert network.countries == {FIRST: "ru"}
    assert [
        body["init_data"] for path, body in network.requests if path == "/me"
    ] == [FIRST]


def test_switch_while_refreshing_profile_reports_restart_and_recovers_controls(
    page,
):
    network = CountryNetwork()
    open_app(page, network, init_data=FIRST)
    network.hold_me = True
    page.get_by_role("button", name="Россия").click()
    for _ in range(100):
        if network.held_me:
            break
        page.wait_for_timeout(25)
    assert len(network.held_me) == 1
    route, _ = network.held_me.pop()
    page.evaluate("auth => { window.__host.wa.initData = auth; }", SECOND)
    route.fulfill(
        json={
            "user_id": FIRST,
            "country": "ru",
            "locale": "ru",
            "currency_symbol": "₽",
            "has_advertiser_profile": False,
            "has_blogger_profile": False,
            "is_manager": False,
        }
    )
    expect(page.locator("#country-error")).not_to_be_empty()
    expect(page.get_by_role("button", name="Россия")).to_be_enabled()
    expect(page.locator("#screen-role-choice")).to_be_hidden()
    assert [
        body["init_data"] for path, body in network.requests if path == "/me"
    ] == [FIRST, FIRST]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_switch_after_me_but_before_modules_finish_does_not_open_old_account(
    page, platform
):
    network = CountryNetwork()
    network.hold_module = True
    page.route("**/*", network.route)
    script = Path(__file__).with_name("miniapp_host_mock.js").read_text()
    script = script.replace("__PLATFORM__", json.dumps(platform))
    script = script.replace("__NATIVE__", json.dumps(False))
    script = script.replace("__INIT_DATA__", json.dumps(FIRST))
    page.add_init_script(script=script)
    template = "app.html" if platform == "telegram" else "max_app.html"
    page.goto(f"http://miniapp.test/miniapp/{template}", wait_until="commit")
    page.wait_for_function(
        "window._me && window._me.user_id === 'synthetic-first-account'"
    )
    assert len(network.held_module) == 1
    page.evaluate("auth => { window.__host.wa.initData = auth; }", SECOND)
    network.held_module.pop().fulfill(path=MINIAPP / "umc-shell.js")
    expect(page.locator("#screen-loading")).to_have_attribute(
        "data-failed", "true"
    )
    expect(page.locator("#screen-country-select")).to_be_hidden()
    assert not [path for path, _ in network.requests if path == "/set-country"]
