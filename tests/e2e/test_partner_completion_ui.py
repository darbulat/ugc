"""Real partner UI against synthetic signed HTTP boundaries."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_home_displays_referral_link_and_clickable_both_side_rates(
    page, platform
):
    network = PartnerNetwork()
    network.partner["current_rates"] = {
        "client_bps": 1000,
        "creator_bps": 1200,
        "overrides": [],
    }
    errors = open_app(page, network, platform, init_data=SIGNED)
    home = page.locator(".screen.active")
    expect(home.locator("[data-partner-link]")).to_have_attribute(
        "href",
        "https://max.ru/synthetic_umc_max?start=ref_abcd1234"
        if platform == "max"
        else network.partner["referral"]["link"],
        timeout=1000,
    )
    expect(home.locator("[data-partner-rate]")).to_contain_text("12%")
    home.locator("[data-partner-rate]").click()
    expect(page.locator("#screen-partner")).to_be_visible()
    assert not errors


class AdminNetwork(PartnerNetwork):
    def __init__(self):
        super().__init__()
        self.partner["capabilities"] = {"manage_overrides": True}
        self.partner["writes_paused"] = False
        self.commands = []

    def route(self, route):
        if route.request.url.endswith("/admin/rate-overrides/list"):
            route.fulfill(json=[])
            return
        if route.request.url.endswith("/admin/rate-overrides/command"):
            body = route.request.post_data_json
            self.commands.append(body)
            route.fulfill(
                json={
                    "action": body["action"],
                    "operation_key": body["operation_key"],
                    "override": {"approval": {"rate_bps": body["rate_bps"]}},
                }
            )
            return
        super().route(route)


def test_admin_override_requires_review_then_sends_real_scoped_command(page):
    network = AdminNetwork()
    errors = open_app(
        page, network, "telegram", init_data=SIGNED, query="?view=partner"
    )
    form = page.locator("#partner-override-admin")
    expect(form).to_be_visible(timeout=1000)
    page.locator("#override-recipient").fill(
        "10000000-0000-4000-8000-000000000002"
    )
    page.locator("#override-policy").fill("published-v2")
    page.locator("#override-side").select_option("creator")
    page.locator("#override-rate").fill("20")
    page.locator("#override-from").fill("2026-11-01T00:00:00+03:00")
    page.locator("#override-until").fill("2027-11-01T00:00:00+03:00")
    page.locator("#override-reason").fill("Индивидуальное соглашение")
    page.locator("#override-review").click()
    assert network.commands == []
    page.locator("#override-confirm").click()
    expect(page.locator("#override-status")).to_contain_text("Сохранено")
    assert len(network.commands) == 1
    command = network.commands[0]
    assert command["side"] == "creator" and command["rate_bps"] == 2000
    assert command["reason"] == "Индивидуальное соглашение"
    assert command["init_data"] == SIGNED and "actor_id" not in command
    assert command["effective_from"].endswith("Z")
    assert not errors


def test_cabinet_renders_public_identity_work_counts_and_pending_reason(page):
    network = PartnerNetwork()
    member = network.partner["network"]["members"][0]
    member.update(
        display_name="Invited creator",
        telegram_username="invited_author",
        work={"active_orders": 2, "completed_works": 3},
    )
    network.partner["financial"]["pending"] = {
        "total": 1,
        "entries": [
            {
                "order_id": "own-order",
                "kind": "creator_referral",
                "amount_minor": "5000",
                "reason": "awaiting_counterparty",
                "waiting_for": [
                    {
                        "role": "creator",
                        "display_name": "Invited creator",
                        "telegram_username": "invited_author",
                    }
                ],
                "due_at": "2026-10-27T12:00:00Z",
            }
        ],
    }
    network.partner["financial"]["management_summary"] = {
        "successful_works": 2,
        "unit_minor": "60000",
        "gross_minor": "120000",
    }
    errors = open_app(
        page, network, "telegram", init_data=SIGNED, query="?view=partner"
    )
    expect(page.locator("#partner-network")).to_contain_text("@invited_author")
    expect(page.locator("#partner-network")).to_contain_text(
        "Активные заказы: 2"
    )
    expect(page.locator("#partner-pending")).to_contain_text("Invited creator")
    expect(page.locator("#partner-management-summary")).to_contain_text("2 ×")
    assert not errors
