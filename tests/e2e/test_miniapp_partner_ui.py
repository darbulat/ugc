"""Production partner UI with synthetic data only at the signed API boundary."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.miniapp_helpers import generate_init_data
from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
SIGNED = generate_init_data("test-token", 101, "synthetic-partner")
ASSIGNMENT = "10000000-0000-4000-8000-000000000001"


def fixture_view():
    balances = {
        key: "0"
        for key in (
            "pending",
            "hold",
            "available",
            "reserved",
            "paid",
            "cancelled",
            "blocked",
            "debt",
        )
    }
    balances["pending"] = "5000"
    return {
        "actor_id": "10000000-0000-4000-8000-000000000002",
        "as_of": "2026-10-23T12:00:00Z",
        "account_status": "active",
        "writes_paused": True,
        "referral": {"link": "https://t.me/synthetic_umc?start=ref_abcd1234"},
        "grade": {
            "verified_creators": 1,
            "threshold": 0,
            "tier_rate_bps": 1000,
            "next_threshold": 100,
            "remaining": 99,
        },
        "standards": {
            "client_first_year_bps": 1000,
            "after_year_bps": 300,
            "creator_tiers": [
                {"threshold": n, "rate_bps": b}
                for n, b in ((0, 1000), (100, 1200), (200, 1500), (400, 2000))
            ],
        },
        "overrides": {"state": "available", "entries": []},
        "network": {
            "total": 1,
            "page": 0,
            "has_more": False,
            "members": [
                {
                    "member_id": "10000000-0000-4000-8000-000000000003",
                    "registered_at": "2026-10-22T12:00:00Z",
                    "status": "active",
                    "roles": ["creator"],
                    "socials": [
                        {
                            "platform": "instagram",
                            "url": "https://instagram.com/synthetic_creator",
                            "verified": True,
                            "verification_source": "canonical_profile",
                            "followers_count": None,
                            "metrics_source": None,
                            "metrics_fetched_at": None,
                        }
                    ],
                }
            ],
        },
        "financial": {
            "state": "ready",
            "currency": "RUB",
            "balances": balances,
            "projection": balances,
            "groups": [
                {
                    "kind": kind,
                    "balances": balances
                    if kind == "creator_referral"
                    else {k: "0" for k in balances},
                    "obligations_count": 1 if kind == "creator_referral" else 0,
                }
                for kind in (
                    "client_referral",
                    "creator_referral",
                    "management",
                )
            ],
            "history": {
                "page": 0,
                "has_more": False,
                "entries": [
                    {
                        "movement_id": "movement-1",
                        "order_id": "actual-synthetic-order",
                        "paid_item_id": "item-1",
                        "kind": "creator_referral",
                        "base_minor": "50000",
                        "rate_bps": 1000,
                        "rate_source": "standard",
                        "policy_version": "synthetic-approved-v1",
                        "snapshot_at": "2026-10-22T12:00:00Z",
                        "amount_minor": "5000",
                        "movement_type": "issuance",
                        "bucket_from": None,
                        "bucket_to": "pending",
                        "effective_at": "2026-10-22T12:00:00Z",
                        "recorded_at": "2026-10-22T12:00:00Z",
                    }
                ],
            },
        },
        "assignments": {
            "state": "available",
            "page": 0,
            "total": 1,
            "has_more": False,
            "entries": [
                {
                    "assignment_id": ASSIGNMENT,
                    "order_id": "actual-synthetic-order",
                    "state": "in_progress",
                    "due_at": "2026-10-25T12:00:00Z",
                }
            ],
        },
    }


class PartnerNetwork(MiniAppNetwork):
    def __init__(self, role="client", locale="ru"):
        super().__init__(
            locale if locale in ("ru", "en", "kk") else "ru",
            registered=role == "client",
        )
        self.locale = locale
        self.blogger_registered = role == "creator"
        self.manager = role == "manager"
        self.partner = fixture_view()
        self.partner_code = 200

    def route(self, route):
        path = urlparse(route.request.url).path
        if "/collaborations/" in path:
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                status=503, json={"detail": "Financial core disabled"}
            )
            return
        if path.endswith("/partner/view"):
            body = route.request.post_data_json
            self.requests.append(("/partner/view", body))
            if body.get("platform") == "max":
                self.partner["referral"]["link"] = (
                    "https://max.ru/synthetic_umc_max?start=ref_abcd1234"
                )
            for key in ("network", "assignments"):
                field = (
                    "assignment_page"
                    if key == "assignments"
                    else "network_page"
                )
                self.partner[key]["page"] = body.get(field, 0)
            route.fulfill(
                status=self.partner_code,
                json=self.partner
                if self.partner_code == 200
                else {"detail": "Unavailable"},
            )
            return
        if path.endswith("/me") and self.locale in ("be", "uz"):
            self.requests.append(("/me", route.request.post_data_json))
            route.fulfill(
                json={
                    "locale": self.locale,
                    "country": "ru",
                    "currency_symbol": "₽",
                    "has_advertiser_profile": True,
                    "has_blogger_profile": False,
                    "is_manager": False,
                }
            )
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("role", ["client", "creator", "manager"])
def test_partner_entry_all_roles_and_exact_signed_read(page, platform, role):
    network = PartnerNetwork(role)
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator(".screen.active [data-partner-open]").click()
    expect(page.locator("#screen-partner")).to_be_visible()
    expect(page.locator("#partner-link")).to_have_attribute(
        "href", network.partner["referral"]["link"]
    )
    expect(page.locator("#partner-network")).to_contain_text(
        "synthetic_creator"
    )
    expect(page.locator("#partner-history")).to_contain_text(
        "actual-synthetic-order"
    )
    request = next(
        body for path, body in network.requests if path == "/partner/view"
    )
    assert request == {
        "init_data": SIGNED,
        "platform": platform,
        "network_page": 0,
        "history_page": 0,
        "assignment_page": 0,
    }
    assert not page.locator("#screen-partner [data-payout]").count()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,title",
    [
        ("ru", "Партнёрский кабинет"),
        ("en", "Partner cabinet"),
        ("kk", "Серіктес кабинеті"),
        ("be", "Партнёрскі кабінет"),
        ("uz", "Hamkor kabineti"),
    ],
)
def test_partner_native_deep_link_locales_and_narrow_visual(
    page, platform, locale, title
):
    page.set_viewport_size({"width": 320, "height": 850})
    network = PartnerNetwork(locale=locale)
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    expect(page.locator("#screen-partner")).to_be_visible()
    expect(page.locator("#partner-title")).to_have_text(title)
    expect(page.locator("#partner-loading")).to_be_empty()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"partner-{platform}-{locale}-320-light")
    assert not errors


@pytest.mark.parametrize("state", ["unavailable", "uninitialized", "mismatch"])
def test_partner_financial_state_never_invents_available_income(page, state):
    network = PartnerNetwork(locale="en")
    network.partner["financial"]["state"] = state
    if state != "mismatch":
        network.partner["financial"].update(
            balances=None,
            projection=None,
            groups=[],
            history={"entries": [], "page": 0, "has_more": False},
        )
    open_app(page, network, query="?view=partner")
    expect(page.locator("#partner-financial-status")).not_to_be_empty()
    expect(page.locator("#partner-financial-status")).to_have_attribute(
        "data-state", state
    )
    if state != "mismatch":
        assert not page.locator("#partner-balances [data-money]").count()


def test_partner_unsafe_link_unknown_metrics_and_session_failure(page):
    network = PartnerNetwork(locale="en")
    network.partner["network"]["members"][0]["socials"][0]["url"] = (
        'javascript:alert("not executed")'
    )
    open_app(page, network, query="?view=partner")
    expect(page.locator("#partner-network")).to_contain_text("Unknown")
    assert not page.locator('#partner-network a[href^="javascript:"]').count()
    network.partner_code = 401
    page.locator("#btn-partner-reload").click()
    expect(page.locator("#partner-error")).to_contain_text("Reopen")
    expect(page.locator("#partner-content")).to_be_hidden()


def test_partner_large_integer_money_pagination_and_copy_fallback(page):
    network = PartnerNetwork(locale="en")
    network.partner["financial"]["balances"]["pending"] = "9007199254740993"
    network.partner["network"]["has_more"] = True
    open_app(page, network, init_data=SIGNED, query="?view=partner")
    expect(
        page.locator('#partner-balances > dl [data-bucket="pending"] dd')
    ).to_have_text("90\u00a0071\u00a0992\u00a0547\u00a0409,93\u00a0RUB")
    page.locator("#btn-partner-copy").click()
    expect(page.locator("#partner-copy-status")).to_contain_text(
        "Copy it manually"
    )
    page.locator("#partner-network button").filter(has_text="Next").click()
    expect(page.locator("#screen-partner")).to_have_attribute(
        "aria-busy", "false"
    )
    assert any(
        body.get("network_page") == 1
        for path, body in network.requests
        if path == "/partner/view"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_partner_assignment_opens_real_screen_and_native_back_returns(
    page, platform
):
    network = PartnerNetwork("manager", "en")
    errors = open_app(
        page,
        network,
        platform,
        native=True,
        init_data=SIGNED,
        query="?view=partner",
    )
    page.locator("#partner-assignments button").filter(
        has_text="Open collaboration"
    ).click()
    expect(page.locator("#screen-collaboration")).to_be_visible()
    expect(page.locator("#collaboration-error")).to_contain_text("unavailable")
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-partner")).to_be_visible()
    assert "assignment=" not in page.url
    assert not errors


def test_partner_native_back_preserves_dashboard_and_dark_visual(page):
    network = PartnerNetwork("client", "ru")
    errors = open_app(page, network, native=True, init_data=SIGNED)
    page.locator(".screen.active [data-partner-open]").click()
    expect(page.locator("#partner-loading")).to_be_empty()
    page.evaluate(
        "window.__host.wa.colorScheme='dark'; "
        "window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    screenshot(page, "partner-telegram-ru-dark")
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    assert "view=partner" not in page.url
    assert not errors
