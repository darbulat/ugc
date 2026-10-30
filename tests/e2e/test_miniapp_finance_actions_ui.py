"""Current admin operational queues and frozen selection closure controls."""

import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import MiniAppNetwork, open_app

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ID = "11111111-2222-4333-8444-555555555555"


class Network(MiniAppNetwork):
    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/admin/partners/context"):
            route.fulfill(
                content_type="application/json",
                body=json.dumps({"capabilities": {"review_leads": True}}),
            )
        elif path.endswith("/collaborations/admin/disputes"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                content_type="application/json",
                body=json.dumps(
                    {
                        "items": [
                            {
                                "assignment_id": ID,
                                "order_id": ID,
                                "reason": "Synthetic dispute",
                                "evidence": "Synthetic evidence",
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    }
                ),
            )
        elif path.endswith("/selection/close"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                content_type="application/json",
                body=json.dumps({"order_id": ID, "closed": True}),
            )
        elif path.endswith("/corrections/admin/apply"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                content_type="application/json",
                body=json.dumps({"applied": True}),
            )
        else:
            super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_admin_disputes_and_exact_reviewed_apply_ui(page, platform):
    network = Network(registered=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-finance-open]").click()
    expect(page.locator("#screen-finance-actions")).to_contain_text(
        "Synthetic dispute"
    )
    assert [r for r in network.requests if r[0].endswith("/admin/disputes")][0][
        1
    ]["limit"] == 25
    page.evaluate("window.__umcAppBridge.showScreen('screen-corrections')")
    page.evaluate(
        "detail=>document.dispatchEvent(new CustomEvent("
        "'umc:correction-detail',{detail}))",
        {
            "case": {
                "case_id": ID,
                "current": {"version": 4, "source_hash": "a" * 64},
                "allowed_actions": ["apply"],
                "applicable_matches": [
                    {"match_id": ID, "intent_id": ID, "observation_id": ID}
                ],
            },
            "context": {
                "admin": True,
                "writes_paused": False,
                "capabilities": {"apply": True},
            },
        },
    )
    page.locator("#finance-correction-apply").click()
    panel = page.locator("#screen-finance-actions details").first
    panel.locator("summary").click()
    panel.locator("[name=reason]").fill("Synthetic reviewed application")
    panel.locator("[name=evidence_reference]").fill("synthetic:proof")
    panel.locator("[name=evidence_hash]").fill("b" * 64)
    panel.locator("[type=submit]").click()
    expect(page.locator("#finance-actions-receipt")).to_contain_text("true")
    result = [r for r in network.requests if r[0].endswith("/admin/apply")][0][
        1
    ]
    assert result["match_id"] == ID and result["expected_version"] == 4
    assert result["expected_source_hash"] == "a" * 64
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_selection_close_uses_frozen_policy_and_explicit_evidence(
    page, platform
):
    network = Network(registered=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-selection')")
    page.evaluate(
        "detail=>document.dispatchEvent(new CustomEvent("
        "'umc:selection-view',{detail}))",
        {
            "order_id": ID,
            "writes_paused": False,
            "closure_policy": {
                "mode": "manual",
                "anchor": "closed_at",
                "refund_window_seconds": 86400,
                "closed_at": None,
                "can_close": True,
            },
        },
    )
    page.locator("#finance-selection-policy").click()
    panel = page.locator("#screen-finance-actions details").first
    panel.locator("summary").click()
    panel.locator("[name=reason]").fill("Synthetic all positions resolved")
    panel.locator("[name=evidence]").fill("synthetic:closure-proof")
    panel.locator("[type=submit]").click()
    expect(page.locator("#finance-actions-receipt")).to_contain_text("true")
    request = [
        r for r in network.requests if r[0].endswith("/selection/close")
    ][0][1]
    assert request["reason"] == "Synthetic all positions resolved"
    assert request["evidence"] == "synthetic:closure-proof"
    assert "refund_window_seconds" not in request
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("decision", ["continue", "cancel"])
def test_explicit_accompaniment_management_review(page, platform, decision):
    network = Network(registered=True)

    original = network.route
    network.route = lambda intercept: route_management(
        intercept, network, original, decision
    )
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-finance-open]").click()
    panel = page.locator("#screen-finance-actions details").filter(
        has=page.locator("[name=decision]")
    )
    panel.locator("summary").click()
    panel.locator("[name=paid_item_id]").fill(ID)
    panel.locator("[name=application_id]").fill(ID)
    panel.locator("[name=expected_work_version]").fill("4")
    panel.locator("[name=decision]").select_option(decision)
    panel.locator("[name=reason]").fill(
        "Synthetic reviewed management decision"
    )
    panel.locator("[name=evidence_reference]").fill(
        "synthetic:management-proof"
    )
    panel.locator("[name=evidence_hash]").fill("c" * 64)
    panel.locator("[type=submit]").click()
    expect(page.locator("#finance-actions-receipt")).to_contain_text(decision)
    result = [
        r
        for r in network.requests
        if r[0].endswith("/accompaniment/management")
    ][0][1]
    assert (
        result["decision"] == decision and result["expected_work_version"] == 4
    )
    assert result["application_id"] == ID
    assert not errors


def route_management(intercept, network, original, decision):
    if urlparse(intercept.request.url).path.endswith(
        "/accompaniment/management"
    ):
        network.requests.append(
            (intercept.request.url, intercept.request.post_data_json)
        )
        intercept.fulfill(
            content_type="application/json",
            body=json.dumps({"decision": decision, "work_version": 5}),
        )
    else:
        original(intercept)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_explicit_refund_before_initialized_work_uses_version_zero(
    page, platform
):
    network = Network(registered=True)
    original = network.route

    def route(intercept):
        if intercept.request.url.endswith("/accompaniment/apply"):
            network.requests.append(
                (intercept.request.url, intercept.request.post_data_json)
            )
            intercept.fulfill(json=dict(applied=True, application_id=ID))
        else:
            original(intercept)

    network.route = route
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-manager-orders')")
    page.locator("#screen-manager-orders [data-finance-open]").click()
    panel = page.locator("#screen-finance-actions details").filter(
        has=page.locator("[name=observation_id]")
    )
    panel.locator("summary").click()
    expect(panel.locator("[name=expected_work_version]")).to_have_attribute(
        "min", "0"
    )
    for name, value in dict(
        paid_item_id=ID,
        observation_id=ID,
        expected_work_version="0",
        reviewed_customer_target_minor="2000",
        reviewed_manager_target_minor="0",
        reason="Synthetic reviewed absence of work",
        evidence_reference="synthetic:absence-proof",
        evidence_hash="e" * 64,
    ).items():
        panel.locator("[name=" + name + "]").fill(value)
    panel.locator("[type=submit]").click()
    expect(page.locator("#finance-actions-receipt")).to_contain_text("true")
    command = [
        body
        for path, body in network.requests
        if path.endswith("/accompaniment/apply")
    ][0]
    assert command["expected_work_version"] == 0
    assert command["reviewed_manager_target_minor"] == "0"
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("can_close", [False, True])
def test_per_item_policy_explains_maturity_without_close_action(
    page, platform, can_close
):
    network = Network(registered=True)
    errors = open_app(page, network, platform)
    page.evaluate("window.__umcAppBridge.showScreen('screen-selection')")
    page.evaluate(
        "detail=>document.dispatchEvent(new CustomEvent("
        "'umc:selection-view',{detail}))",
        {
            "order_id": ID,
            "writes_paused": False,
            "closure_policy": {
                "mode": "per_item_v1",
                "anchor": "item_delivered",
                "refund_window_seconds": 604800,
                "closed_at": None,
                "can_close": can_close,
            },
        },
    )
    page.locator("#finance-selection-policy").click()
    panel = page.locator("#screen-finance-actions")
    expect(panel).to_contain_text("каждой переданной позиции")
    expect(panel).to_contain_text("7 дней")
    expect(panel).to_contain_text("14 дней")
    assert panel.locator("form").count() == 0
    assert not [
        r for r in network.requests if r[0].endswith("/selection/close")
    ]
    assert not errors
