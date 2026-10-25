"""Native reviewed grants preserve exact evidence after unknown outcomes."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ID = "11111111-2222-4333-8444-555555555555"


class Network(MiniAppNetwork):
    def __init__(self, allowed=True, rejected=False):
        super().__init__(registered=True)
        self.allowed, self.rejected = allowed, rejected
        self.attempts = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/me"):
            route.fulfill(
                json=dict(
                    user_id=ID,
                    locale="ru",
                    country="ru",
                    currency_symbol="₽",
                    has_advertiser_profile=True,
                    has_blogger_profile=False,
                    is_manager=True,
                )
            )
        elif path.endswith("/financial/grants/admin/context"):
            route.fulfill(
                json=dict(
                    actor_id=ID,
                    can_approve=self.allowed,
                    can_mature=self.allowed,
                    writes_paused=False,
                )
            )
        elif path.endswith("/financial/grants/admin/approve"):
            self.attempts.append(route.request.post_data_json)
            if len(self.attempts) == 1:
                route.fulfill(
                    status=409 if self.rejected else 500,
                    json={"detail": "synthetic_rejection"},
                )
            else:
                route.fulfill(
                    json=dict(
                        grant_id=ID,
                        obligation_id=ID,
                        amount_minor=self.attempts[-1]["amount_minor"],
                        currency="RUB",
                        release_at="2026-11-08T00:00:00Z",
                        state="hold",
                    )
                )
        elif path.endswith("/financial/grants/admin/mature"):
            self.attempts.append(route.request.post_data_json)
            route.fulfill(
                json=dict(
                    grant_id=ID, mature=False, release_at="2026-11-08T00:00:00Z"
                )
            )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_grant_review_unknown_retry_exact_amount_and_hold(page, platform):
    network = Network()
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-manual-grant-open]").click()
    screen = page.locator("#screen-manual-grants")
    screen.locator("summary").filter(has_text="Создать начисление").click()
    for name, value in dict(
        paid_item_id=ID,
        recipient_id=ID,
        amount_minor="9007199254740993",
        reason="Synthetic reviewed positive adjustment",
        evidence_reference="synthetic:positive-proof",
        evidence_hash="f" * 64,
    ).items():
        screen.locator("[name=" + name + "]").fill(value)
    screen.get_by_role(
        "button", name="Проверить операцию", exact=True
    ).first.click()
    expect(screen).to_contain_text("9007199254740993")
    assert network.attempts == []
    screen.locator("#manual-grant-confirm").click()
    expect(screen.locator("#manual-grant-retry")).to_be_visible()
    expect(screen.locator("#manual-grant-reset")).to_have_count(0)
    screen.locator("#manual-grant-retry").click()
    expect(screen).to_contain_text("Начисление создано в холде")
    expect(screen).to_contain_text("2026-11-08T00:00:00Z")
    assert len(network.attempts) == 2
    assert network.attempts[0] == network.attempts[1]
    assert network.attempts[1]["amount_minor"] == "9007199254740993"
    assert (
        network.attempts[1]["evidence_reference"] == "synthetic:positive-proof"
    )
    screen.locator("summary").filter(
        has_text="Проверить окончание холда"
    ).click()
    screen.locator("[name=grant_id]").fill(ID)
    screen.get_by_role(
        "button", name="Проверить операцию", exact=True
    ).last.click()
    screen.locator("#manual-grant-confirm").click()
    expect(screen).to_contain_text("Средства остаются в холде")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_grant_definitive_rejection_explicit_reset_and_denied_entry(
    page, platform
):
    network = Network(rejected=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCManualGrants.open()")
    screen = page.locator("#screen-manual-grants")
    screen.locator("summary").filter(has_text="Создать начисление").click()
    for name, value in dict(
        paid_item_id=ID,
        recipient_id=ID,
        amount_minor="100",
        reason="Synthetic adjustment",
        evidence_reference="synthetic:proof",
        evidence_hash="f" * 64,
    ).items():
        screen.locator("[name=" + name + "]").fill(value)
    screen.get_by_role(
        "button", name="Проверить операцию", exact=True
    ).first.click()
    screen.locator("#manual-grant-confirm").click()
    screen.locator("#manual-grant-reset").click()
    expect(screen.locator("[name=amount_minor]")).to_have_value("")
    assert len(network.attempts) == 1
    network.allowed = False
    page.evaluate("window.UMCManualGrants.open()")
    expect(screen).to_contain_text("Нет подтверждённого доступа")
    expect(screen.locator("form")).to_have_count(0)
    assert not errors
