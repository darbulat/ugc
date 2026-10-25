"""Admin dispute review uses its own signed view, preserving party privacy."""

from dataclasses import replace
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_collaboration_ui import (
    ASSIGNMENT,
    SIGNED_DATA,
    CollaborationNetwork,
)
from tests.e2e.test_miniapp_design_system import open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class Network(CollaborationNetwork):
    def __init__(self):
        super().__init__(
            state="disputed", actions=["resolve_success", "resolve_failure"]
        )
        self.admin_reads = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/admin/partners/context"):
            route.fulfill(json={"capabilities": {"review_leads": True}})
        elif path.endswith("/collaborations/admin/disputes"):
            route.fulfill(
                json=dict(
                    items=[
                        dict(
                            assignment_id=str(ASSIGNMENT),
                            order_id=str(ASSIGNMENT),
                            reason="Synthetic admin dispute",
                        )
                    ],
                    has_more=False,
                )
            )
        elif path.endswith(f"/collaborations/admin/{ASSIGNMENT}/view"):
            self.admin_reads.append(route.request.post_data_json)
            route.fulfill(json=self.response())
        elif path.endswith(f"/collaborations/{ASSIGNMENT}/status"):
            route.fulfill(
                status=403, json={"detail": "collaboration_view_forbidden"}
            )
        elif path.endswith(f"/collaborations/{ASSIGNMENT}/command"):
            body = route.request.post_data_json
            self.commands.append(body)
            work = self.record.collaboration.resolve_dispute(
                success=True,
                reason=body["reason"],
                evidence=body["evidence"],
                at=self.now,
            )
            self.record = replace(
                self.record, collaboration=work, version=self.record.version + 1
            )
            self.actions = []
            route.fulfill(json=self.response())
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_dispute_queue_opens_admin_view_and_ordinary_open_remains_denied(
    page, platform
):
    network = Network()
    errors = open_app(page, network, platform, init_data=SIGNED_DATA)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-finance-open]").click()
    page.locator("#screen-finance-actions").get_by_role(
        "button", name="Открыть работу", exact=True
    ).click()
    screen = page.locator("#screen-collaboration")
    screen.locator('[data-collaboration-action="resolve_success"]').click()
    screen.locator("#collaboration-reason").fill(
        "Synthetic admin evidence review"
    )
    screen.locator("#collaboration-evidence").fill("synthetic:review-proof")
    screen.locator("#btn-collaboration-submit").click()
    expect(screen.locator("#collaboration-status")).to_have_attribute(
        "data-state", "success_final"
    )
    assert network.admin_reads[0]["platform"] == platform
    assert network.commands[0]["action"] == "resolve_success"
    assert network.commands[0]["reason"] == "Synthetic admin evidence review"
    page.evaluate("value=>window.UMCCollaboration.open(value)", str(ASSIGNMENT))
    expect(screen.locator("#collaboration-error")).to_contain_text(
        "нет доступа"
    )
    expect(screen.locator("#collaboration-details")).to_be_hidden()
    assert not errors
