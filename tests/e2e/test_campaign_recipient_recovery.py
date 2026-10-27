"""Recipient recovery through real settings, navigation and signed requests."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_campaign_runtime import CAMPAIGN
from tests.e2e.test_miniapp_campaign_settings import CampaignNetwork
from tests.e2e.test_miniapp_design_system import open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class RecipientNetwork(CampaignNetwork):
    def __init__(self, locale="ru"):
        super().__init__(locale=locale)
        self.settings["consent"] = {
            "version": 1,
            "active": True,
            "effective": True,
        }
        self.settings["can_consent"] = False
        self.settings["can_unsubscribe"] = True
        self.choice = None
        self.version = 0
        self.hold_view = False
        self.hold_response = False
        self.held_views = []
        self.held_responses = []
        self.abort_response = False

    def view(self):
        allowed = (
            ["interested", "declined"]
            if self.settings["consent"]["effective"]
            else []
        )
        if self.choice and self.choice != "withdrawn":
            allowed.append("withdrawn")
        return {
            "campaign_id": CAMPAIGN,
            "content": {
                "title": "Private network invitation",
                "text": "Private task body",
            },
            "sender_label": "Synthetic owner",
            "version": self.version,
            "choice": self.choice,
            "allowed_choices": allowed,
            "as_of": "2026-10-27T10:00:00Z",
        }

    def receipt(self):
        return {
            "campaign_id": CAMPAIGN,
            "version": 1,
            "choice": "interested",
        }

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/recipient/view"):
            self.requests.append((path, route.request.post_data_json))
            if self.hold_view:
                self.held_views.append(route)
            else:
                route.fulfill(json=self.view())
        elif path.endswith("/recipient/respond"):
            self.requests.append((path, route.request.post_data_json))
            self.choice = "interested"
            self.version = 1
            if self.hold_response:
                self.held_responses.append(route)
            elif self.abort_response:
                route.abort("failed")
            else:
                route.fulfill(json=self.receipt())
        elif path.endswith("/owned/report"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                json={
                    "campaign_id": CAMPAIGN,
                    "delivery": {"accepted": 2, "unknown": 1},
                    "responses": {"interested": 1, "withdrawn": 1},
                    "as_of": "2026-10-27T10:00:00Z",
                    "accepted_means": "provider_accepted_not_read",
                }
            )
        else:
            super().route(route)

    def responses(self):
        return [
            body
            for path, body in self.requests
            if path.endswith("/recipient/respond")
        ]


def enter(page, network, platform):
    errors = open_app(page, network, platform, query="?campaign=" + CAMPAIGN)
    expect(page.locator("#screen-campaign-recipient")).to_be_visible()
    expect(page.locator("#campaign-response-interested")).to_be_visible()
    return errors


def unsubscribe(page):
    expect(page.locator("#screen-campaign-settings")).to_be_visible()
    page.locator("#btn-campaign-unsubscribe").click()
    expect(page.locator("#btn-campaign-consent")).to_be_visible()
    expect(page.locator("#screen-campaign-settings")).to_have_attribute(
        "aria-busy", "false"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_settings_back_reloads_exact_campaign_after_unsubscribe(page, platform):
    network = RecipientNetwork()
    errors = enter(page, network, platform)
    page.evaluate(
        "window.staleResponse = "
        "document.querySelector('#campaign-response-interested')"
    )
    page.locator("#campaign-recipient-settings").click()
    unsubscribe(page)
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#screen-campaign-recipient")).to_be_visible()
    expect(page.locator("#campaign-response-interested")).to_have_count(0)
    expect(page.locator("#campaign-response-declined")).to_have_count(0)
    page.evaluate("window.staleResponse.click()")
    assert not network.responses()
    views = [
        body
        for path, body in network.requests
        if path.endswith("/recipient/view")
    ]
    assert len(views) == 2
    assert all(body["campaign_id"] == CAMPAIGN for body in views)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_response_keeps_exact_retry_after_settings_and_back(
    page, platform
):
    network = RecipientNetwork()
    errors = enter(page, network, platform)
    network.abort_response = True
    page.locator("#campaign-response-interested").click()
    expect(page.locator("#campaign-response-retry")).to_be_enabled()
    original = network.responses()[0]
    page.locator("#campaign-recipient-settings").click()
    unsubscribe(page)
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#campaign-response-retry")).to_be_enabled()
    assert len(network.responses()) == 1
    network.abort_response = False
    page.locator("#campaign-response-retry").click()
    expect(page.locator("#campaign-response-retry")).to_have_count(0)
    expect(page.locator("#campaign-response-withdrawn")).to_be_visible()
    expect(page.locator("#campaign-response-interested")).to_have_count(0)
    assert network.responses() == [original, original]
    assert original["campaign_id"] == CAMPAIGN
    assert original["expected_version"] == 0
    assert original["choice"] == "interested"
    assert original["operation_key"].startswith("campaign-response:")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_recipient_back_preserves_unknown_response_until_explicit_retry(
    page, platform
):
    network = RecipientNetwork()
    errors = enter(page, network, platform)
    network.abort_response = True
    page.locator("#campaign-response-interested").click()
    expect(page.locator("#campaign-response-retry")).to_be_enabled()
    original = network.responses()[0]
    page.locator("#campaign-recipient-back").click()
    expect(page.locator("#screen-campaign-recipient")).to_be_hidden()
    page.evaluate(
        "window.__umcAppBridge.showScreen('screen-campaign-recipient')"
    )
    expect(page.locator("#campaign-response-retry")).to_be_enabled()
    assert network.responses() == [original]
    network.abort_response = False
    page.locator("#campaign-response-retry").click()
    expect(page.locator("#campaign-response-retry")).to_have_count(0)
    assert network.responses() == [original, original]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("outcome", ["confirmed", "unknown"])
def test_hidden_response_settles_and_return_refreshes_consent(
    page, platform, outcome
):
    network = RecipientNetwork()
    errors = enter(page, network, platform)
    network.hold_response = True
    page.locator("#campaign-response-interested").click()
    expect(page.locator("#screen-campaign-recipient")).to_have_attribute(
        "aria-busy", "true"
    )
    page.evaluate("window.UMCCampaignSettings.open()")
    unsubscribe(page)
    assert len(network.held_responses) == 1
    held = network.held_responses.pop()
    if outcome == "unknown":
        held.abort("failed")
    else:
        held.fulfill(json=network.receipt())
    expect(page.locator("#screen-campaign-recipient")).to_have_attribute(
        "aria-busy", "false"
    )
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#screen-campaign-recipient")).to_be_visible()
    expect(page.locator("#campaign-response-interested")).to_have_count(0)
    if outcome == "unknown":
        expect(page.locator("#campaign-response-retry")).to_be_enabled()
    else:
        expect(page.locator("#campaign-response-withdrawn")).to_be_enabled()
    assert len(network.responses()) == 1
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_hidden_view_completion_cannot_restore_stale_choices(page, platform):
    network = RecipientNetwork()
    network.hold_view = True
    stale_view = network.view()
    errors = open_app(page, network, platform, query="?campaign=" + CAMPAIGN)
    expect(page.locator("#screen-campaign-recipient")).to_have_attribute(
        "aria-busy", "true"
    )
    page.evaluate("window.UMCCampaignSettings.open()")
    unsubscribe(page)
    assert len(network.held_views) == 1
    network.hold_view = False
    network.held_views.pop().fulfill(json=stale_view)
    expect(page.locator("#screen-campaign-recipient")).to_have_attribute(
        "aria-busy", "false"
    )
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#campaign-recipient-task")).to_be_visible()
    expect(page.locator("#campaign-response-interested")).to_have_count(0)
    expect(page.locator("#campaign-recipient-refresh")).to_be_enabled()
    assert not network.responses()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("event", ["focus", "visibilitychange"])
def test_account_change_clears_hidden_private_data_and_pending_retry(
    page, platform, event
):
    network = RecipientNetwork()
    errors = enter(page, network, platform)
    network.abort_response = True
    page.locator("#campaign-response-interested").click()
    expect(page.locator("#campaign-response-retry")).to_be_enabled()
    page.locator("#campaign-recipient-settings").click()
    expect(page.locator("#btn-campaign-back")).to_be_enabled()
    page.evaluate(
        "event => { window.__host.wa.initData = 'another-synthetic-account';"
        "(event === 'focus' ? window : document)"
        ".dispatchEvent(new Event(event)); }",
        event,
    )
    page.locator("#btn-campaign-back").click()
    expect(page.locator("#screen-campaign-recipient")).to_be_visible()
    expect(page.locator("#campaign-recipient-task")).to_have_count(0)
    expect(page.locator("#campaign-response-retry")).to_have_count(0)
    expect(page.locator("#campaign-recipient-status")).not_to_be_empty()
    assert len(network.responses()) == 1
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    ("locale", "unknown", "accepted", "withdrawn"),
    [
        ("ru", "Результат неизвестен: 1", "Принято ботом: 2", "Отозвано: 1"),
        ("en", "Unknown result: 1", "Accepted by bot: 2", "Withdrawn: 1"),
        ("kk", "Нәтиже белгісіз: 1", "Бот қабылдады: 2", "Қайтарылды: 1"),
        ("be", "Вынік невядомы: 1", "Прынята ботам: 2", "Адклікана: 1"),
        ("uz", "Natija noma’lum: 1", "Bot qabul qildi: 2", "Qaytarildi: 1"),
    ],
)
def test_report_unknown_is_an_aggregate_not_a_retry_instruction(
    page, platform, locale, unknown, accepted, withdrawn
):
    network = RecipientNetwork(locale)
    errors = enter(page, network, platform)
    page.evaluate("id => window.UMCCampaignRuntime.openReport(id)", CAMPAIGN)
    delivery = page.locator("#screen-campaign-recipient article").first
    expect(delivery).to_contain_text(unknown)
    expect(delivery).to_contain_text(accepted)
    expect(
        page.locator("#screen-campaign-recipient article").nth(1)
    ).to_contain_text(withdrawn)
    expect(page.locator("#campaign-response-retry")).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    ("entry", "screen"),
    [
        ("assignment", "collaboration"),
        ("assignment_id", "collaboration"),
        ("selection", "selection"),
        ("selection_id", "blogger-dashboard"),
    ],
)
def test_conflicting_assignment_and_selection_links_keep_entry_priority(
    page, platform, entry, screen
):
    network = RecipientNetwork()
    errors = open_app(
        page,
        network,
        platform,
        query=f"?campaign={CAMPAIGN}&{entry}={CAMPAIGN}",
    )
    page.wait_for_function("window.__umcAppReady === true")
    expect(page.locator(f"#screen-{screen}")).to_be_visible()
    expect(page.locator("#screen-campaign-recipient")).to_be_hidden()
    assert not any(
        path.endswith("/recipient/view") for path, _ in network.requests
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_duplicate_campaign_link_cannot_choose_an_arbitrary_invitation(
    page, platform
):
    network = RecipientNetwork()
    errors = open_app(
        page,
        network,
        platform,
        query=f"?campaign={CAMPAIGN}&campaign={CAMPAIGN}",
    )
    page.wait_for_function("window.__umcAppReady === true")
    expect(page.locator("#screen-blogger-dashboard")).to_be_visible()
    expect(page.locator("#screen-campaign-recipient")).to_be_hidden()
    assert not any(
        path.endswith("/recipient/view") for path, _ in network.requests
    )
    assert not errors
