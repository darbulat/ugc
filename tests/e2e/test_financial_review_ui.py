"""Late reviews pin real facts across native unknown retries."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ID = "11111111-2222-4333-8444-555555555555"
MONEY = "9007199254740993"


class Network(MiniAppNetwork):
    def __init__(self, rejected=False):
        super().__init__(registered=True)
        self.rejected = rejected
        self.denied = False
        self.case = None
        self.opened, self.resolved = [], []
        self.viewed = []
        self.ground = dict(
            business_key="actual-issued-ground",
            obligation_id=ID,
            kind="creator_referral",
            recipient_id=ID,
            paid_item_id=ID,
            amount_minor=MONEY,
            current_source_hash="a" * 64,
            buckets=dict(paid=MONEY, available="0", reserved="0"),
        )

    def _open(self, route):
        body = route.request.post_data_json
        self.opened.append(body)
        if len(self.opened) == 1:
            route.fulfill(
                status=409 if self.rejected else 500,
                json={"detail": "synthetic_first_outcome"},
            )
        else:
            self.case = dict(
                self.ground,
                case_id=ID,
                version=1,
                state="open",
                current_source_hash="b" * 64,
            )
            route.fulfill(json=self.case)

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
        elif path.endswith("/admin/partners/context"):
            route.fulfill(json={"capabilities": {"review_leads": True}})
        elif path.endswith("/financial/reviews/admin/context"):
            route.fulfill(
                status=403 if self.denied else 200,
                json=dict(
                    actor_id=ID,
                    writes_paused=False,
                    cases=[self.case] if self.case else [],
                    grounds=[self.ground],
                    has_more=False,
                    page=0,
                ),
            )
        elif path.endswith("/financial/reviews/admin/" + ID + "/view"):
            self.viewed.append(route.request.post_data_json)
            route.fulfill(json=self.case)
        elif path.endswith("/financial/reviews/admin/open"):
            self._open(route)
        elif path.endswith("/financial/reviews/admin/resolve"):
            body = route.request.post_data_json
            self.resolved.append(body)
            if len(self.resolved) == 1:
                route.fulfill(status=500, json={"detail": "synthetic_unknown"})
            else:
                self.case = dict(self.case, version=2, state="resolved")
                route.fulfill(
                    json=dict(
                        self.case,
                        decision=body["decision"],
                        target_minor=body["target_minor"],
                        cancelled_delta_minor=body["target_minor"] or "0",
                        debt_created_minor=body["target_minor"] or "0",
                    )
                )
        elif path.endswith("/financial/grants/admin/context"):
            route.fulfill(
                json=dict(
                    actor_id=ID,
                    can_approve=False,
                    can_mature=False,
                    writes_paused=False,
                )
            )
        elif path.endswith(
            (
                "/payouts/read/admin/queue",
                "/financial/corrections/admin/queue",
                "/collaborations/admin/disputes",
                "/financial/debts/admin/context",
                "/financial/replacements/queue",
            )
        ):
            route.fulfill(status=503, json={"detail": "synthetic_unavailable"})
        else:
            super().route(route)


def fill_proof(screen):
    screen.locator("[name=reason]").fill("Synthetic reviewed late evidence")
    screen.locator("[name=evidence_reference]").fill("synthetic:late-proof")
    screen.locator("[name=evidence_hash]").fill("e" * 64)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_paid_review_durable_exact_open_and_cancellation_retries(
    page, platform
):
    network = Network()
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCFinancialReviews.open()")
    screen = page.locator("#screen-financial-reviews")
    screen.locator("[data-financial-review-ground]").click()
    expect(screen).to_contain_text(MONEY + " RUB")
    fill_proof(screen)
    screen.locator("#financial-review-form [type=submit]").click()
    assert not network.opened
    screen.locator("#financial-review-confirm").click()
    expect(screen.locator("#financial-review-retry")).to_be_visible()
    expect(screen.locator("#financial-review-reset")).to_have_count(0)
    page.evaluate("window.UMCFinancialReviews.open()")
    screen.locator("#financial-review-retry").click()
    expect(screen).to_contain_text("Результат подтверждён")
    assert network.opened[0] == network.opened[1]
    assert network.opened[1]["expected_source_hash"] == "a" * 64
    assert "actor_id" not in network.opened[1]
    screen.get_by_role("button", name="Просмотреть случай", exact=True).click()
    screen.locator("[name=decision]").select_option("cumulative_cancel")
    screen.locator("[name=target_minor]").fill(MONEY)
    fill_proof(screen)
    screen.locator("#financial-review-form [type=submit]").click()
    assert not network.resolved
    screen.locator("#financial-review-confirm").click()
    screen.locator("#financial-review-retry").click()
    expect(screen).to_contain_text("Создано задолженности, копейки")
    assert network.resolved[0] == network.resolved[1]
    assert network.resolved[1]["target_minor"] == MONEY
    assert network.resolved[1]["expected_version"] == 1
    assert network.resolved[1]["expected_source_hash"] == "b" * 64
    network.denied = True
    page.evaluate("window.UMCFinancialReviews.open()")
    expect(screen).to_contain_text("Нет подтверждённого доступа администратора")
    expect(screen).not_to_contain_text(MONEY)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_definitive_review_conflict_reset_refreshes_source_before_new_decision(
    page, platform
):
    network = Network(rejected=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCFinancialReviews.open()")
    screen = page.locator("#screen-financial-reviews")
    screen.locator("[data-financial-review-ground]").click()
    fill_proof(screen)
    screen.locator("#financial-review-form [type=submit]").click()
    screen.locator("#financial-review-confirm").click()
    expect(screen.locator("#financial-review-reset")).to_be_visible()
    network.ground["current_source_hash"] = "c" * 64
    screen.locator("#financial-review-reset").click()
    screen.locator("[data-financial-review-ground]").click()
    fill_proof(screen)
    screen.locator("#financial-review-form [type=submit]").click()
    screen.locator("#financial-review-confirm").click()
    expect(screen).to_contain_text("Результат подтверждён")
    assert (
        network.opened[0]["operation_key"] != network.opened[1]["operation_key"]
    )
    assert network.opened[1]["expected_source_hash"] == "c" * 64
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_common_hub_opens_exact_case_and_no_adjustment_keeps_null_target(
    page, platform
):
    network = Network()
    network.case = dict(
        network.ground,
        case_id=ID,
        version=1,
        state="open",
        current_source_hash="b" * 64,
    )
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCFinanceHub.open()")
    row = page.locator('[data-finance-queue="financial_reviews"] article')
    expect(row).to_contain_text("actual-issued-ground")
    row.get_by_role("button", name="Открыть проверку", exact=True).click()
    screen = page.locator("#screen-financial-reviews")
    expect(screen.locator("[name=decision]")).to_have_value("no_adjustment")
    expect(screen.locator("[name=target_minor]")).to_be_hidden()
    fill_proof(screen)
    screen.locator("#financial-review-form [type=submit]").click()
    screen.locator("#financial-review-confirm").click()
    screen.locator("#financial-review-retry").click()
    expect(screen).to_contain_text("Результат подтверждён")
    assert network.resolved[-1]["case_id"] == ID
    assert network.resolved[-1]["decision"] == "no_adjustment"
    assert network.resolved[-1]["target_minor"] is None
    assert len(network.viewed) == 1
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_reserved_case_links_existing_payout_review_and_keeps_case_open(
    page, platform
):
    network = Network()
    network.case = dict(
        network.ground,
        case_id=ID,
        version=1,
        state="open",
        current_source_hash="b" * 64,
        buckets=dict(paid="0", reserved=MONEY, available="0"),
    )
    errors = open_app(page, network, platform)
    page.evaluate(
        "window.__reviewPayout=[];window.UMCPayoutAdmin={open:mode=>window.__reviewPayout.push(mode)}"
    )
    page.evaluate("value=>window.UMCFinancialReviews.open(value)", ID)
    screen = page.locator("#screen-financial-reviews")
    expect(screen).to_contain_text("Сохраните этот случай открытым")
    screen.locator("#financial-review-payout").click()
    assert page.evaluate("window.__reviewPayout") == ["queue"]
    assert network.case["state"] == "open"
    assert not network.opened and not network.resolved
    assert not errors
