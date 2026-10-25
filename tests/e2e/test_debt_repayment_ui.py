"""Native reviewed recovery retains unknown operations with exact proof."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_partner_ui import SIGNED, PartnerNetwork

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ID = "11111111-2222-4333-8444-555555555555"


class Network(PartnerNetwork):
    def __init__(self):
        super().__init__()
        self.attempts = []
        self.remaining = "3000"
        self.paid = "5000"
        self.applied = False

    def route(self, route):
        path = route.request.url
        if path.endswith("/me"):
            route.fulfill(
                json={
                    "user_id": self.partner["actor_id"],
                    "locale": "ru",
                    "country": "ru",
                    "currency_symbol": "₽",
                    "has_advertiser_profile": True,
                    "has_blogger_profile": False,
                    "is_manager": True,
                }
            )
        elif path.endswith("/financial/debts/admin/context"):
            route.fulfill(
                json={
                    "actor_id": self.partner["actor_id"],
                    "cases": [
                        {
                            "obligation_id": ID,
                            "business_key": "synthetic-obligation",
                            "recipient_id": ID,
                            "currency": "RUB",
                            "case_id": ID,
                            "debt_minor": self.remaining,
                        }
                    ],
                    "observations": [
                        {
                            "observation_id": ID,
                            "recipient_id": ID,
                            "case_id": ID,
                            "amount_minor": "2000",
                            "currency": "RUB",
                            "proof_claimed": True,
                            "bank_reference": "synthetic-incoming",
                            "evidence_reference": "synthetic-proof",
                            "application_id": ID if self.applied else None,
                        }
                    ],
                    "has_more": False,
                }
            )
        elif path.endswith("/financial/debts/admin/apply"):
            self.attempts.append(route.request.post_data_json)
            if len(self.attempts) == 1:
                route.fulfill(status=500, json={"detail": "synthetic_unknown"})
            else:
                self.remaining = "1000"
                self.applied = True
                route.fulfill(
                    json={
                        "applied": True,
                        "recovered_minor": "2000",
                        "remaining_debt_minor": "1000",
                    }
                )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_debt_review_and_unknown_retry_keep_exact_operation_and_proof(
    page, platform
):
    network = Network()
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?view=partner"
    )
    page.locator("#screen-partner [data-debt-open]").click()
    screen = page.locator("#screen-debts")
    screen.locator("#debt-apply-" + ID).click()
    screen.locator("[name=reason]").fill(
        "Synthetic recognized incoming receipt"
    )
    screen.locator("[name=evidence_reference]").fill("synthetic:bank-proof")
    screen.locator("[name=evidence_hash]").fill("d" * 64)
    screen.get_by_role("button", name="Проверка операции", exact=True).click()
    assert network.attempts == []
    screen.locator("#debt-confirm").click()
    expect(screen.locator("#debt-retry")).to_be_visible()
    screen.locator("#debt-retry").click()
    expect(screen).to_contain_text("1000 RUB")
    assert (
        len(network.attempts) == 2
        and network.attempts[0] == network.attempts[1]
    )
    assert network.attempts[0]["expected_debt_minor"] == "3000"
    assert network.attempts[0]["evidence_reference"] == "synthetic:bank-proof"
    assert network.paid == "5000"
    assert not errors
