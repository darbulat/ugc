"""Actual MAX consent UI; no live identities, sends or invoices."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_checkout_ui import CheckoutNetwork, open_selection
from tests.e2e.test_miniapp_design_system import screenshot

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
CHALLENGE = "99000000-0000-4000-8000-000000000001"
CLAIM = "99000000-0000-4000-8000-000000000002"
TOKEN = "lk1_" + "A" * 43
URL = "https://t.me/actual_test_bot?start=" + TOKEN


class LinkingNetwork(CheckoutNetwork):
    def __init__(self, locale="en"):
        super().__init__(locale)
        self.value["telegram_handoff"] = None
        self.link_requests = []
        self.unknown = False
        self.link = dict(
            state="not_requested",
            challenge_id=None,
            version=0,
            claim_id=None,
            expires_at=None,
            telegram_identity=None,
            enabled=True,
            can_create=True,
            can_confirm=False,
            can_revoke=False,
            launch_url=None,
            receipt=None,
        )

    def propose(self):
        self.link.update(
            state="proposed",
            version=2,
            claim_id=CLAIM,
            telegram_identity={
                "id": "777",
                "display_name": "<img src=x onerror=alert(1)>",
                "username": "actual_tg",
            },
            can_confirm=True,
        )

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.startswith("/miniapp/api/messenger-links/telegram/"):
            kind = path.rsplit("/", 1)[1]
            self.link_requests.append((kind, route.request.post_data_json))
            if kind == "challenge":
                self.link.update(
                    state="waiting",
                    challenge_id=CHALLENGE,
                    version=1,
                    expires_at=(
                        datetime.now(timezone.utc) + timedelta(minutes=10)
                    ).isoformat(),
                    can_create=False,
                    can_revoke=True,
                    launch_url=URL,
                )
            elif kind == "confirm":
                self.link.update(
                    state="linked",
                    version=3,
                    can_confirm=False,
                    can_revoke=False,
                    launch_url=None,
                )
            elif kind == "revoke":
                self.link.update(
                    state="revoked",
                    version=self.link["version"] + 1,
                    can_create=True,
                    can_confirm=False,
                    can_revoke=False,
                    launch_url=None,
                )
            if self.unknown and kind != "status":
                route.abort("failed")
                return
            route.fulfill(json=self.link)
            return
        super().route(route)


def open_linking(page, network):
    errors = open_selection(page, network, "max")
    assert page.locator("#umc-checkout-link-account").count() == 1, (
        "MAX linking entry is missing"
    )
    page.locator("#umc-checkout-link-account").click()
    expect(page.locator("#screen-messenger-linking")).to_be_visible()
    expect(page.locator("#messenger-linking-status")).not_to_be_empty()
    return errors


def test_max_linking_requires_three_explicit_clicks_and_actual_server_identity(
    page,
):
    network = LinkingNetwork()
    errors = open_linking(page, network)
    assert [kind for kind, _ in network.link_requests] == ["status"]
    page.locator("#messenger-linking-create").click()
    expect(page.locator("#messenger-linking-open")).to_be_visible()
    assert all(
        call != ["link", URL] for call in page.evaluate("window.__host.calls")
    )
    page.locator("#messenger-linking-open").click()
    assert page.evaluate("window.__host.calls").count(["link", URL]) == 1
    assert "confirm" not in [kind for kind, _ in network.link_requests]
    network.propose()
    page.locator("#messenger-linking-refresh").click()
    expect(page.locator("#messenger-linking-identity")).to_contain_text("777")
    expect(page.locator("#messenger-linking-identity")).to_contain_text("<img")
    assert page.locator("#messenger-linking-identity img").count() == 0
    page.locator("#messenger-linking-confirm").click()
    expect(page.locator("#messenger-linking-status")).to_have_attribute(
        "data-state", "linked"
    )
    confirm = next(
        body for kind, body in network.link_requests if kind == "confirm"
    )
    assert confirm["claim_id"] == CLAIM and confirm["expected_version"] == 2
    assert "telegram_id" not in confirm and confirm["platform"] == "max"
    assert not any(
        path.endswith("/invoice") for path, _ in network.checkout_requests
    )
    assert errors == []


def test_unknown_command_preserves_safe_intent_after_reload(
    page,
):
    network = LinkingNetwork()
    open_linking(page, network)
    network.unknown = True
    page.locator("#messenger-linking-create").click()
    expect(page.locator("#messenger-linking-retry")).to_be_visible()
    saved = page.evaluate("JSON.stringify(sessionStorage)")
    assert TOKEN not in saved and "launch_url" not in saved
    initial = [
        body for kind, body in network.link_requests if kind == "challenge"
    ][0]
    network.unknown = False
    page.reload()
    expect(page.locator("#screen-selection")).to_be_visible()
    page.locator("#umc-checkout-link-account").click()
    expect(page.locator("#messenger-linking-retry")).to_be_visible()
    assert (
        len([1 for kind, _ in network.link_requests if kind == "challenge"])
        == 1
    )
    page.locator("#messenger-linking-retry").click()
    expect(page.locator("#messenger-linking-retry")).to_be_hidden()
    repeated = [
        body for kind, body in network.link_requests if kind == "challenge"
    ]
    assert repeated[0] == repeated[1] == initial
    assert TOKEN not in page.evaluate(
        "JSON.stringify(sessionStorage)+JSON.stringify(localStorage)+location.href+document.body.innerHTML"
    )


@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
@pytest.mark.parametrize("dark", [False, True])
def test_linking_disabled_is_localized_fits_320_and_native_back(
    page, locale, dark
):
    page.set_viewport_size({"width": 320, "height": 720})
    page.emulate_media(color_scheme="dark" if dark else "light")
    network = LinkingNetwork(locale)
    network.link.update(state="unavailable", enabled=False, can_create=False)
    errors = open_linking(page, network)
    page.evaluate(
        "window.__host.wa.colorScheme=" + ("'dark'" if dark else "'light'")
    )
    page.evaluate(
        "window.__host.events.themeChanged&&window.__host.events.themeChanged()"
    )
    expect(page.locator("#messenger-linking-status")).to_have_attribute(
        "data-state", "unavailable"
    )
    expect(page.locator("#messenger-linking-create")).to_be_hidden()
    expect(page.locator("#messenger-linking-title")).not_to_be_empty()
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert len(network.link_requests) == 1
    screenshot(
        page, f"messenger-linking-{locale}-" + ("dark" if dark else "light")
    )
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-selection")).to_be_visible()
    assert errors == []


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "https://t.me@evil.test/bot?start=" + TOKEN,
        "https://evil.test/bot?start=" + TOKEN,
    ],
)
def test_server_url_is_whitelisted_and_not_written_to_dom(page, bad_url):
    network = LinkingNetwork()
    open_linking(page, network)
    page.locator("#messenger-linking-create").click()
    network.link["launch_url"] = bad_url
    page.locator("#messenger-linking-refresh").click()
    expect(page.locator("#messenger-linking-open")).to_be_hidden()
    assert bad_url not in page.content()


def test_telegram_host_does_not_offer_general_linking_or_mutate_checkout(page):
    network = LinkingNetwork()
    open_selection(page, network, "telegram")
    expect(page.locator("#umc-checkout-link-account")).to_be_hidden()
    assert network.link_requests == []


def test_linking_has_no_launch_when_host_lacks_capability_or_request_is_revoked(
    page,
):
    network = LinkingNetwork()
    open_linking(page, network)
    page.evaluate("window.WebApp.openLink=undefined")
    page.locator("#messenger-linking-create").click()
    expect(page.locator("#messenger-linking-open")).to_be_hidden()
    page.locator("#messenger-linking-revoke").click()
    expect(page.locator("#messenger-linking-status")).to_have_attribute(
        "data-state", "revoked"
    )
    expect(page.locator("#messenger-linking-confirm")).to_be_hidden()
    assert not any(kind == "confirm" for kind, _ in network.link_requests)


def test_expiry_clears_launch_and_confirmation_without_automatic_renewal(page):
    network = LinkingNetwork()
    open_linking(page, network)
    page.locator("#messenger-linking-create").click()
    network.link["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(milliseconds=200)
    ).isoformat()
    page.locator("#messenger-linking-refresh").click()
    expect(page.locator("#messenger-linking-open")).to_be_hidden(timeout=700)
    assert (
        len([kind for kind, _ in network.link_requests if kind == "challenge"])
        == 1
    )
    assert not any(kind == "confirm" for kind, _ in network.link_requests)
