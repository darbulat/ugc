"""Chat registration buttons open the selected role without another choice."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_country_identity import CountryNetwork
from tests.e2e.test_miniapp_design_system import (
    MINIAPP,
    MiniAppNetwork,
    open_app,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ROLES = ["advertiser", "blogger"]

LEAFLET_MOCK = """
window.L = {
  map(id) {
    const element = document.getElementById(id);
    element.classList.add("leaflet-container");
    return {
      setView() { return this; },
      invalidateSize() {},
      on(_, callback) {
        element.addEventListener("click", () => {
          callback({latlng: {lat: 55.5, lng: 49.1}});
        });
      },
    };
  },
  tileLayer() { return {addTo() {}}; },
  marker() { return {addTo() { return this; }, setLatLng() {}}; },
};
"""


class MapNetwork(MiniAppNetwork):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.css = None
        self.hold_css = False
        self.fail_css = False
        self.fail_js = False

    def route(self, route):
        url = urlsplit(route.request.url)
        if url.hostname == "unpkg.com":
            asset = url.path.rsplit("/", 1)[-1]
            self.assets.append(asset)
            if asset == "leaflet.js":
                if self.fail_js:
                    route.abort()
                else:
                    route.fulfill(
                        body=LEAFLET_MOCK, content_type="text/javascript"
                    )
            elif self.hold_css:
                self.css = route
            elif self.fail_css:
                route.abort()
            else:
                route.fulfill(body="", content_type="text/css")
        elif url.path == "/miniapp/api/geocode/reverse":
            self.requests.append(
                ("/geocode/reverse", route.request.post_data_json)
            )
            route.fulfill(
                json={
                    "city": "Map city",
                    "region": "Synthetic region",
                    "country": "Synthetic country",
                }
            )
        else:
            super().route(route)


class MixedVersionMapNetwork(MapNetwork):
    def __init__(self, legacy_asset):
        super().__init__()
        self.legacy_asset = legacy_asset
        self.blogger_registered = True
        self.blogger_agreement_confirmed = True
        self.blogger_city = "Saved city"

    def route(self, route):
        asset = urlsplit(route.request.url).path.removeprefix("/miniapp/")
        if self.legacy_asset == "script" and asset == "umc-creator-form.js":
            # Preserved from main before the Leaflet change (blob 3ec60695).
            legacy_script = (
                Path(__file__)
                .with_name("fixtures")
                .joinpath("legacy-creator-form.js")
            )
            route.fulfill(path=legacy_script, content_type="text/javascript")
        elif self.legacy_asset == "template" and asset in (
            "app.html",
            "max_app.html",
        ):
            # Restore the legacy map markup and the eager Leaflet references.
            template = (MINIAPP / asset).read_text()
            template = template.replace(
                '<div id="blg-city-map-status" role="status"></div>', "", 1
            ).replace(
                "<head>",
                """<head>
  <link rel="stylesheet" crossorigin="anonymous"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script crossorigin="anonymous"
          src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>""",
                1,
            )
            route.fulfill(body=template, content_type="text/html")
        else:
            super().route(route)


def open_registration(page, network, platform, role):
    query = f"?view=register-{role}" if platform == "telegram" else ""
    errors = open_app(page, network, platform, query=query)
    if platform == "max":
        page.locator(f'[data-role="{role}"]').click()
    return errors


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("has_other_profile", [False, True])
def test_registration_link_opens_selected_form(page, role, has_other_profile):
    network = MiniAppNetwork(registered=role == "blogger" and has_other_profile)
    network.blogger_registered = role == "advertiser" and has_other_profile
    network.advertiser_agreed = False
    network.blogger_agreement_confirmed = False
    errors = open_app(page, network, query=f"?view=register-{role}")
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator("#screen-role-choice")).to_be_hidden()
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_survives_country_selection(page, role):
    network = CountryNetwork()
    errors = open_app(page, network, query=f"?view=register-{role}")
    expect(page.locator("#screen-country-select")).to_be_visible()
    page.get_by_role("button", name="Россия").click()
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator("#screen-role-choice")).to_be_hidden()
    assert len(network.countries) == 1
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_keeps_first_input_and_resumes_draft(page, role):
    network = MiniAppNetwork()
    errors = open_app(page, network, query=f"?view=register-{role}")
    field = page.locator("#adv-brand" if role == "advertiser" else "#blg-name")
    draft = page.locator(f'[data-profile-draft="{role}"]')
    field.fill("Unfinished profile")
    expect(field).to_have_value("Unfinished profile")
    expect(draft).to_contain_text("Черновик сохранён на этом устройстве")

    page.reload()
    expect(page.locator(f"#screen-register-{role}")).to_be_visible()
    expect(page.locator(f"#form-{role}")).to_be_hidden()
    draft.get_by_role(
        "button", name="Продолжить заполнение", exact=True
    ).click()
    expect(field).to_have_value("Unfinished profile")
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("agreed", [False, True])
def test_old_registration_link_reuses_existing_profile(page, role, agreed):
    network = MiniAppNetwork(registered=True)
    network.blogger_registered = True
    network.advertiser_agreed = agreed
    network.blogger_agreement_confirmed = agreed
    errors = open_app(page, network, query=f"?view=register-{role}")
    screen = (
        f"screen-{role}-dashboard" if agreed else f"screen-agreements-{role}"
    )
    expect(page.locator("#" + screen)).to_be_visible()
    expect(page.locator(f"#screen-register-{role}")).to_be_hidden()
    assert not any(
        path.startswith("/register/") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("role", ROLES)
def test_registration_link_still_requires_telegram_session(page, role):
    network = MiniAppNetwork()
    open_app(page, network, query=f"?view=register-{role}", init_data="")
    expect(page.locator("#screen-loading")).to_have_attribute(
        "data-failed", "true"
    )
    expect(page.locator(f"#screen-register-{role}")).to_be_hidden()
    assert not network.requests


def test_unknown_registration_role_keeps_normal_role_choice(page):
    network = MiniAppNetwork()
    errors = open_app(page, network, query="?view=register-manager")
    expect(page.locator("#screen-role-choice")).to_be_visible()
    assert not errors


@pytest.mark.parametrize(
    "role,prefix", [("advertiser", "adv"), ("blogger", "blg")]
)
@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_profile_can_be_submitted_from_registration(
    page, role, prefix, platform
):
    network = MiniAppNetwork()
    errors = open_registration(page, network, platform, role)
    page.locator(f"#{prefix}-name").fill("Synthetic account")
    if role == "advertiser":
        page.locator("#adv-phone").fill("89001234567")
        page.locator("#adv-brand").fill("Synthetic brand")
    else:
        page.locator("#blg-instagram").fill("@synthetic_creator")
        page.locator("#blg-birth-year").select_option("1995")
        page.locator("#blg-topics").fill("beauty, fashion")
        page.locator("#blg-audience-geo").fill("Россия, Казань")
        page.locator("#blg-price").fill("10000")
        page.locator("#btn-blogger-city-map").click()
        page.locator("#blg-city-search").fill("Synthetic city")
        page.locator("#blg-city-search").press("Enter")
        expect(page.locator("#blg-city")).to_have_value("Synthetic city")
        page.locator("#btn-blogger-city-confirm").click()
    page.locator(f"#btn-submit-{role}").click()
    expect(page.locator(f"#screen-agreements-{role}")).to_be_visible()
    page.locator(f"#{prefix}-agree-checkbox").check()
    page.locator(f"#btn-confirm-{prefix}-agreement").click()
    expect(page.locator(f"#screen-{role}-dashboard")).to_be_visible()
    assert [
        path for path, _ in network.requests if path.startswith("/register/")
    ] == [f"/register/{role}", f"/register/{role}/confirm-agreement"]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_map_loads_only_on_open_and_waits_for_css(page, platform):
    network = MapNetwork()
    network.hold_css = True
    errors = open_registration(page, network, platform, "blogger")
    toggle = page.locator("#btn-blogger-city-map")
    status = page.locator("#blg-city-map-status")
    map_canvas = page.locator("#blogger-city-map")
    expect(toggle).to_be_enabled()
    assert network.assets == []

    toggle.click()
    expect(status).to_have_text("Загрузка…")
    toggle.click()
    expect(status).to_be_hidden()
    toggle.click()
    expect(status).to_have_text("Загрузка…")
    page.wait_for_function("typeof window.L?.map === 'function'")
    assert sorted(network.assets) == ["leaflet.css", "leaflet.js"]
    expect(map_canvas).not_to_have_class("leaflet-container")
    assert network.css is not None
    network.css.fulfill(body="", content_type="text/css")

    expect(map_canvas).to_have_class("leaflet-container")
    map_canvas.click()
    expect(page.locator("#blg-city")).to_have_value("Map city")
    page.locator("#btn-blogger-city-confirm").click()
    expect(page.locator("#blg-lat")).to_have_value("55.5")
    expect(page.locator("#blg-lon")).to_have_value("49.1")
    toggle.click()
    expect(map_canvas).to_be_visible()
    assert sorted(network.assets) == ["leaflet.css", "leaflet.js"]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_map_failure_allows_search_and_retry(page, platform):
    network = MapNetwork()
    network.fail_css = True
    errors = open_registration(page, network, platform, "blogger")
    toggle = page.locator("#btn-blogger-city-map")
    status = page.locator("#blg-city-map-status")
    map_canvas = page.locator("#blogger-city-map")

    toggle.click()
    expect(status).to_contain_text("Не удалось загрузить карту")
    page.locator("#blg-city-search").fill("Synthetic city")
    page.locator("#blg-city-search").press("Enter")
    expect(page.locator("#blg-city")).to_have_value("Synthetic city")
    page.locator("#btn-blogger-city-confirm").click()
    expect(toggle).to_have_attribute("aria-expanded", "false")

    network.fail_css = False
    toggle.click()
    expect(map_canvas).to_have_class("leaflet-container")
    expect(status).to_be_empty()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("legacy_asset", ["template", "script"])
def test_map_works_with_mixed_template_and_script(page, platform, legacy_asset):
    network = MixedVersionMapNetwork(legacy_asset)
    errors = open_app(page, network, platform)
    page.locator("#btn-blogger-update-profile").click()
    expect(page.locator("#screen-register-blogger")).to_be_visible()
    expect(page.locator("#blg-city")).to_have_value("Saved city")
    assets = ["leaflet.css", "leaflet.js"]
    assert sorted(network.assets) == (
        assets if legacy_asset == "template" else []
    )

    toggle = page.locator("#btn-blogger-city-map")
    canvas = page.locator("#blogger-city-map")
    toggle.click()
    expect(canvas).to_have_class("leaflet-container")
    canvas.click()
    expect(page.locator("#blg-city")).to_have_value("Map city")
    page.locator("#btn-blogger-city-confirm").click()
    expect(page.locator("#blg-lat")).to_have_value("55.5")
    expect(page.locator("#blg-lon")).to_have_value("49.1")
    toggle.click()
    expect(canvas).to_be_visible()
    assert sorted(network.assets) == assets
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("failed_asset", ["css", "js"])
def test_legacy_map_script_recovers_after_loading_failure(
    page, platform, failed_asset
):
    network = MixedVersionMapNetwork("script")
    network.fail_css = failed_asset == "css"
    network.fail_js = failed_asset == "js"
    errors = open_app(page, network, platform)
    page.locator("#btn-blogger-update-profile").click()
    toggle = page.locator("#btn-blogger-city-map")
    toggle.click()
    expect(page.locator("#blg-city-map-status")).to_contain_text(
        "Не удалось загрузить карту"
    )
    page.locator("#blg-city-search").fill("Synthetic city")
    page.locator("#blg-city-search").press("Enter")
    expect(page.locator("#blg-city")).to_have_value("Synthetic city")
    page.locator("#btn-blogger-city-confirm").click()

    network.fail_css = False
    network.fail_js = False
    toggle.click()
    expect(page.locator("#blogger-city-map")).to_have_class("leaflet-container")
    assert network.assets.count(f"leaflet.{failed_asset}") == 2
    successful_asset = "js" if failed_asset == "css" else "css"
    assert network.assets.count(f"leaflet.{successful_asset}") == 1
    assert not errors
