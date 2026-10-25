"""Actual campaign recipient UI with synthetic host and API boundaries."""

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
        if path.endswith("/campaigns/recipient/view"):
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "campaign_id": CAMPAIGN,
                        "content": {
                            "title": "Synthetic invitation",
                            "text": "Task body",
                        },
                        "sender_label": "Synthetic owner",
                        "version": 0,
                        "choice": None,
                        "allowed_choices": ["interested", "declined"],
                    }
                ),
            )
        elif path.endswith("/campaigns/recipient/respond"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "campaign_id": CAMPAIGN,
                        "version": 1,
                        "choice": "interested",
                    }
                ),
            )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_recipient_native_link_reaches_real_response_controls(page, platform):
    network = Network(registered=True)
    errors = open_app(page, network, platform, query="?campaign=" + CAMPAIGN)
    expect(page.locator("#screen-campaign-recipient")).to_be_visible()
    expect(page.locator("#campaign-recipient-task")).to_contain_text(
        "Synthetic invitation"
    )
    page.locator("#campaign-response-interested").click()
    expect(page.locator("#campaign-recipient-status")).not_to_be_empty()
    assert len([x for x in network.requests if x[0].endswith("/respond")]) == 1
    assert not errors
