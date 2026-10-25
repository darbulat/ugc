"""Real replacement forms use only signed commands and explicit review."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED
from tests.e2e.test_partner_admin_ui import Network as AdminNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ITEM = "20000000-0000-4000-8000-000000000001"
INTEREST = "20000000-0000-4000-8000-000000000002"
REQUEST = "20000000-0000-4000-8000-000000000003"
REPLACEMENT = "20000000-0000-4000-8000-000000000004"


class Network(AdminNetwork):
    def __init__(self):
        super().__init__()
        self.operations = []
        self.view = dict(
            actor_id=self.partner["actor_id"],
            paid_item_id=ITEM,
            order_id="own-order",
            assignment_id=ITEM,
            assignment_version=1,
            original_paid_pool=30,
            reserve_limit=6,
            replacement_count=0,
            completed_work=False,
            writes_paused=False,
            capabilities=dict(request=True, review=True),
            candidates=[
                dict(
                    interest_id=INTEREST,
                    creator_id=INTEREST,
                    instagram_url="https://instagram.com/confirmed_reserve",
                )
            ],
            history=[],
        )

    def pending(self):
        self.view["history"] = [
            dict(
                request_id=REQUEST,
                version=1,
                state="pending",
                reason_code="lost_contact",
                reason="Не выходит на связь",
                evidence_reference="support:1",
                replacement_id=None,
                current=False,
            )
        ]

    def route(self, route):
        path = route.request.url.split("/miniapp/api")[-1]
        if path == "/financial/replacements/view":
            route.fulfill(json=self.view)
            return
        if path == "/financial/replacements/queue":
            route.fulfill(
                json=dict(
                    actor_id=self.partner["actor_id"],
                    entries=[],
                    page=0,
                    has_more=False,
                )
            )
            return
        if path.startswith("/financial/replacements/"):
            body = route.request.post_data_json
            self.operations.append((path, body))
            if self.abort_once:
                self.abort_once = False
                route.abort("failed")
                return
            result = dict(operation_key=body["operation_key"], version=1)
            if path.endswith("/request"):
                self.pending()
            elif path.endswith("/decision"):
                self.view["history"][0].update(
                    state="approved",
                    version=2,
                    replacement_id=REPLACEMENT,
                    current=True,
                )
                self.view.update(
                    assignment_version=2, replacement_count=7, candidates=[]
                )
            elif path.endswith("/contact"):
                result["contact"] = dict(
                    display_name="Own replacement", telegram="own_replacement"
                )
            route.fulfill(json=result)
            return
        super().route(route)


def open_replacement(page, network, platform="telegram"):
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    page.add_script_tag(url="http://miniapp.test/miniapp/umc-replacements.js")
    page.evaluate("item => window.UMCReplacements.open(item)", ITEM)
    expect(page.locator("#replacement-request-form")).to_be_visible()
    return errors


def prepare_request(page):
    page.locator("#replacement-reason-code").select_option("lost_contact")
    page.locator("#replacement-reason").fill("Не выходит на связь")
    page.locator("#replacement-evidence").fill("support:1")
    page.locator("#replacement-request-review").click()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_client_request_has_review_and_original_assignment_version(
    page, platform
):
    network = Network()
    errors = open_replacement(page, network, platform)
    expect(page.locator("#screen-replacements")).to_contain_text(
        "Исходный оплаченный пул: 30"
    )
    prepare_request(page)
    assert network.operations == []
    page.locator("#replacement-confirm").click()
    expect(page.locator("#replacement-message")).to_contain_text(
        "Решение сохранено"
    )
    path, values = network.operations[0]
    assert (
        path.endswith("/request") and values["expected_assignment_version"] == 1
    )
    assert (
        values["candidate_interest_id"] == INTEREST
        and values["init_data"] == SIGNED
    )
    assert "actor_id" not in values and "original_paid_pool" not in values
    assert not errors


def test_above_reserve_review_requires_exception_and_contact_is_explicit(page):
    network = Network()
    network.view["replacement_count"] = 6
    network.pending()
    errors = open_replacement(page, network)
    page.locator("#replacement-approve-" + REQUEST).click()
    page.locator("#replacement-decision-reason").fill("Основания подтверждены")
    page.locator("#replacement-decision-evidence").fill("support:review")
    page.locator("#replacement-decision-review").click()
    assert network.operations == []
    expect(page.locator("#replacement-message")).to_contain_text("Проверьте")
    page.locator("#replacement-exception-reason").fill(
        "Дополнительная замена согласована"
    )
    page.locator("#replacement-exception-evidence").fill("agreement:extra")
    page.locator("#replacement-decision-review").click()
    page.locator("#replacement-confirm").click()
    expect(page.locator("#replacement-contact-" + REPLACEMENT)).to_be_visible()
    path, values = network.operations[0]
    assert path.endswith("/decision") and values["expected_version"] == 1
    assert values["exception_evidence"] == "agreement:extra"
    page.locator("#replacement-contact-" + REPLACEMENT).click()
    page.locator("#replacement-contact-reason").fill(
        "Получить согласованную замену"
    )
    page.locator("#replacement-contact-evidence").fill("miniapp:explicit")
    page.locator("#replacement-contact-review").click()
    assert len(network.operations) == 1
    page.locator("#replacement-confirm").click()
    expect(page.locator("#replacement-contact-result")).to_contain_text(
        "own_replacement"
    )
    expect(page.locator("#replacement-contact-result")).to_contain_text(
        "не создаётся"
    )
    assert not errors


def test_unknown_replacement_retries_original_operation(page):
    network = Network()
    network.abort_once = True
    open_replacement(page, network)
    prepare_request(page)
    page.locator("#replacement-confirm").click()
    page.locator("#replacement-retry").click()
    expect(page.locator("#replacement-message")).to_contain_text(
        "Решение сохранено"
    )
    assert (
        len(network.operations) == 2
        and network.operations[0] == network.operations[1]
    )
