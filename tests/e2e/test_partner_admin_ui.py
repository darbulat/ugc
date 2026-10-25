"""Real review forms run against a synthetic signed network boundary."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED
from tests.e2e.test_partner_completion_ui import AdminNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
LEAD = "10000000-0000-4000-8000-000000000010"
FIRST = "10000000-0000-4000-8000-000000000011"
SECOND = "10000000-0000-4000-8000-000000000012"


class Network(AdminNetwork):
    def __init__(self):
        super().__init__()
        self.operations = []
        self.abort_once = False
        self.leads = [
            {
                "lead_id": LEAD,
                "order_id": "own-order",
                "version": 0,
                "selected_ordinals": [1, 7],
                "contact_reference": "client contact",
            }
        ]

    def route(self, route):
        path = route.request.url.split("/miniapp/api")[-1]
        if path == "/admin/partners/context":
            route.fulfill(
                json={
                    "actor_id": self.partner["actor_id"],
                    "capabilities": {
                        "review_leads": True,
                        "correct_binding": True,
                    },
                }
            )
            return
        if path == "/admin/partners/leads":
            route.fulfill(
                json={
                    "entries": self.leads,
                    "page": 0,
                    "total": len(self.leads),
                    "has_more": False,
                }
            )
            return
        if path in (
            "/admin/partners/lead-command",
            "/admin/partners/binding-command",
        ):
            body = route.request.post_data_json
            self.operations.append((path, body))
            if self.abort_once:
                self.abort_once = False
                route.abort("failed")
            else:
                self.leads = []
                route.fulfill(
                    json={"operation_key": body["operation_key"], "version": 1}
                )
            return
        super().route(route)


def open_admin(page, network, platform="telegram"):
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    page.add_script_tag(url="http://miniapp.test/miniapp/umc-leads.js")
    page.locator("#partner-admin-open").click(timeout=1000)
    expect(page.locator("#lead-accept-" + LEAD)).to_be_visible()
    return errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_lead_acceptance_requires_review_and_adds_multiple_managers(
    page, platform
):
    network = Network()
    errors = open_admin(page, network, platform)
    expect(page.locator("#screen-partner-admin")).to_contain_text(
        "не подтверждает оплату"
    )
    page.locator("#lead-accept-" + LEAD).click()
    page.locator("#lead-manager-ids").fill(FIRST + "\n" + SECOND)
    page.locator("#lead-review-reason").fill("Назначены два менеджера")
    page.locator("#lead-review").click()
    assert network.operations == []
    page.locator("#lead-admin-confirm").click()
    expect(page.locator("#lead-admin-message")).to_contain_text(
        "Решение сохранено"
    )
    path, values = network.operations[0]
    assert path == "/admin/partners/lead-command"
    assert values["manager_ids"] == [FIRST, SECOND]
    assert values["expected_version"] == 0 and values["action"] == "accept"
    assert values["init_data"] == SIGNED and "actor_id" not in values
    assert not errors


def test_unknown_review_result_retries_the_same_operation(page):
    network = Network()
    network.abort_once = True
    open_admin(page, network)
    page.locator("#lead-reject-" + LEAD).click()
    page.locator("#lead-review-reason").fill("Нет подходящего менеджера")
    page.locator("#lead-review").click()
    page.locator("#lead-admin-confirm").click()
    page.locator("#lead-admin-retry").click()
    expect(page.locator("#lead-admin-message")).to_contain_text(
        "Решение сохранено"
    )
    assert len(network.operations) == 2
    assert network.operations[0] == network.operations[1]


def test_binding_correction_has_explicit_old_new_identity_and_reason(page):
    network = Network()
    errors = open_admin(page, network)
    page.locator("#screen-partner-admin details summary").click()
    page.locator("#binding-referred").fill(LEAD)
    page.locator("#binding-old").fill(FIRST)
    page.locator("#binding-new").fill(SECOND)
    page.locator("#binding-reason").fill("Техническая ошибка исходной привязки")
    page.locator("#binding-review").click()
    assert network.operations == []
    page.locator("#lead-admin-confirm").click()
    expect(page.locator("#lead-admin-message")).to_contain_text(
        "Решение сохранено"
    )
    path, values = network.operations[0]
    assert path.endswith("/binding-command")
    assert (
        values["referred_id"] == LEAD
        and values["expected_referrer_id"] == FIRST
    )
    assert values["referrer_id"] == SECOND and values["reason"]
    assert not errors
