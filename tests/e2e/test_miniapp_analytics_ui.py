"""Real native UI distinguishes absent metrics and explicit evidence forms."""

import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
CAMPAIGN = "11111111-2222-4333-8444-555555555555"


class Network(MiniAppNetwork):
    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/analytics/owned/report"):
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "subject_type": "campaign",
                        "subject_id": CAMPAIGN,
                        "state": "no_data",
                        "marketing_spend_minor": None,
                        "counts": {
                            "views": None,
                            "leads": None,
                            "paid_sales": None,
                        },
                        "rates": {"cpv": None, "cpl": None, "cpa": None},
                        "currency": None,
                        "sources": [],
                        "paid_pilot_campaigns": 0,
                    }
                ),
            )
        elif path.endswith("/admin/partners/context"):
            route.fulfill(
                content_type="application/json",
                body=json.dumps({"capabilities": {"review_leads": True}}),
            )
        elif path.endswith("/analytics/admin/events/import"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                content_type="application/json", body='{"imported":1}'
            )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_analytics_no_data_and_explicit_admin_import(page, platform):
    network = Network(registered=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.UMCAnalytics.open('campaign', '" + CAMPAIGN + "')")
    expect(page.locator("#screen-analytics")).to_be_visible()
    expect(page.locator("#analytics-cpv")).to_contain_text("Нет данных")
    details = page.locator("#screen-analytics details").filter(
        has=page.locator("#analytics-events")
    )
    details.locator("summary").click()
    details.locator("[name=source_id]").fill(CAMPAIGN)
    details.locator("[name=events]").fill(
        json.dumps(
            [
                {
                    "external_event_id": "synthetic-view",
                    "kind": "view",
                    "occurred_at": "2026-10-24T12:00:00Z",
                    "entity_id": "video",
                    "quantity": 100,
                }
            ]
        )
    )
    details.locator("[type=submit]").click()
    expect(page.locator("#analytics-status")).to_contain_text(
        "Нет подтверждённых данных"
    )
    imported = [x for x in network.requests if x[0].endswith("/events/import")]
    assert len(imported) == 1 and imported[0][1]["events"][0]["quantity"] == 100
    assert imported[0][1]["operation_key"].startswith("analytics:")
    assert not errors
