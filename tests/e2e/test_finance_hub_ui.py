"""Common queue uses protected reads and explicit unavailable states."""

from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ID = "11111111-2222-4333-8444-555555555555"


class Network(MiniAppNetwork):
    denied = False

    def __init__(self):
        super().__init__(registered=True)
        self.reads = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/admin/partners/context"):
            route.fulfill(
                status=403 if self.denied else 200,
                json={"detail": "denied"}
                if self.denied
                else {"capabilities": {"review_leads": True}},
            )
        elif path.endswith("/financial/reviews/admin/context"):
            route.fulfill(status=503, json={"detail": "synthetic_unavailable"})
        elif path.endswith("/financial/grants/admin/context"):
            route.fulfill(
                json=dict(
                    actor_id=ID,
                    can_approve=False,
                    can_mature=False,
                    writes_paused=False,
                )
            )
        elif path.endswith("/payouts/read/admin/queue"):
            self.reads.append((path, route.request.post_data_json))
            route.fulfill(
                json=dict(
                    entries=[
                        dict(
                            request_id=ID,
                            state="reserved",
                            amount_minor="9007199254740993",
                            currency="RUB",
                            block_reason="synthetic_reserved_review",
                        )
                    ],
                    has_more=True,
                    next_cursor="opaque",
                    as_of="2026-10-25T00:00:00Z",
                )
            )
        elif path.endswith("/financial/corrections/admin/queue"):
            self.reads.append((path, route.request.post_data_json))
            route.fulfill(status=503, json={"detail": "synthetic_unavailable"})
        elif path.endswith("/collaborations/admin/disputes"):
            self.reads.append((path, route.request.post_data_json))
            route.fulfill(
                json=dict(
                    items=[
                        dict(
                            assignment_id=ID,
                            order_id=ID,
                            reason="Synthetic disputed work",
                        )
                    ],
                    has_more=False,
                )
            )
        elif path.endswith("/financial/debts/admin/context"):
            self.reads.append((path, route.request.post_data_json))
            route.fulfill(
                json=dict(
                    actor_id=ID,
                    cases=[
                        dict(
                            obligation_id=ID,
                            recipient_id=ID,
                            case_id=ID,
                            debt_minor="2000",
                            currency="RUB",
                        )
                    ],
                    observations=[],
                    has_more=False,
                )
            )
        elif path.endswith("/financial/replacements/queue"):
            self.reads.append((path, route.request.post_data_json))
            route.fulfill(
                json=dict(
                    actor_id=ID,
                    entries=[
                        dict(
                            request_id=ID,
                            paid_item_id=ID,
                            order_id=ID,
                            reason="Synthetic replacement review",
                        )
                    ],
                    has_more=False,
                )
            )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_finance_hub_partial_failure_precise_money_and_existing_review(
    page, platform
):
    network = Network()
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-finance-hub-open]").click()
    screen = page.locator("#screen-finance-hub")
    expect(screen).to_contain_text("9007199254740993 RUB")
    expect(screen).to_contain_text("Synthetic disputed work")
    expect(screen).to_contain_text("Synthetic replacement review")
    expect(
        screen.locator('[data-finance-queue="corrections"]')
    ).to_contain_text("Источник недоступен: наличие записей не подтверждено")
    expect(
        screen.locator('[data-finance-queue="corrections"]')
    ).not_to_contain_text("В этой странице записей нет")
    expect(screen.locator('[data-finance-queue="payouts"]')).to_contain_text(
        "Есть следующие страницы"
    )
    page.evaluate(
        "window.__hubReview=[];window.UMCReplacements={open:id=>window.__hubReview.push(id)}"
    )
    screen.locator('[data-finance-queue="replacements"] article button').click()
    assert page.evaluate("window.__hubReview") == [ID]
    bodies = {
        path.rsplit("/", 2)[-2] + "/" + path.rsplit("/", 1)[-1]: body
        for path, body in network.reads
    }
    assert any(
        body.get("limit") == 20 and body.get("cursor") is None
        for body in bodies.values()
    )
    assert not [body for _, body in network.reads if "operation_key" in body]
    network.denied = True
    page.evaluate("window.UMCFinanceHub.open()")
    expect(screen).to_contain_text("Нет подтверждённого доступа администратора")
    expect(screen.locator("[data-finance-queue]")).to_have_count(0)
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", [401, 403])
def test_hub_revocation_during_parallel_source_reads_clears_every_queue(
    page, platform, status
):
    network = Network()
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCFinanceHub.open()")
    screen = page.locator("#screen-finance-hub")
    expect(screen).to_contain_text("9007199254740993 RUB")

    def deny(route):
        route.fulfill(
            status=status, json={"detail": "current_authority_revoked"}
        )

    page.route("**/collaborations/admin/disputes", deny)
    screen.get_by_role("button", name="Обновить", exact=True).click()
    expect(screen).to_contain_text("Нет подтверждённого доступа администратора")
    expect(screen.locator("[data-finance-queue]")).to_have_count(0)
    expect(screen).not_to_contain_text("9007199254740993")
    assert not errors
