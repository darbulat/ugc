"""Draft reload preserves service mode, positions and quote inputs."""

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app
from tests.e2e.test_miniapp_selection_ui import (
    POLICY,
    SIGNED,
    SelectionNetwork,
    fill,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "mode,all_positions",
    [("with_manager", True), ("with_manager", False), ("self_service", False)],
)
def test_draft_reload_preserves_mode_positions_and_policy(
    page, platform, mode, all_positions
):
    network = SelectionNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    if not all_positions:
        page.locator("#intake-all-manager").uncheck()
        page.locator("#intake-position-1").check()
        page.locator("#intake-position-7").check()
    page.locator('input[name="intake-mode"][value="' + mode + '"]').check()
    due = page.locator("#intake-due").input_value()
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator('input[name="intake-mode"]:checked')).to_have_value(
        mode
    )
    expect(page.locator("#intake-policy")).to_have_value(POLICY)
    expect(page.locator("#intake-product")).to_have_value(
        "https://example.test/real-product"
    )
    expect(page.locator("#intake-honorarium")).to_have_value("999.00")
    expect(page.locator("#intake-due")).to_have_value(due)
    if all_positions:
        expect(page.locator("#intake-all-manager")).to_be_checked()
    else:
        expect(page.locator("#intake-all-manager")).not_to_be_checked()
        expect(page.locator("#intake-position-1")).to_be_checked()
        expect(page.locator("#intake-position-7")).to_be_checked()
        expect(page.locator("#intake-position-2")).not_to_be_checked()
    assert network.creates == [] and not errors


class DraftNetwork(SelectionNetwork):
    def __init__(self):
        super().__init__()
        self.funnels = []
        self.held_funnels = []
        self.hold_opened = False

    def route(self, route):
        from urllib.parse import urlparse

        path = urlparse(route.request.url).path
        if path == "/miniapp/api/financial/orders/policies":
            route.fulfill(
                json={
                    "writes_paused": False,
                    "currency": "RUB",
                    "policies": self.policies,
                    "funnel_tracking": True,
                }
            )
            return
        if path == "/miniapp/api/financial/orders/funnel/stage":
            payload = route.request.post_data_json
            self.funnels.append(payload)
            if self.hold_opened and payload["stage"] == "opened":
                self.held_funnels.append(route)
            else:
                route.fulfill(json={"recorded": True})
            return
        super().route(route)


def switch_draft_identity(page, user, platform, *, ready=True):
    page.evaluate(
        """({user,platform,ready}) => {
      window._me.user_id=user;
      window.__miniapp_platform=platform;
      window.WebApp=window.__host.wa;
      window.Telegram={WebApp:window.__host.wa};
      if(ready){
        document.dispatchEvent(new CustomEvent('umc:app-ready'));
        document.dispatchEvent(new CustomEvent(
          'umc:intake-policy-ready',{detail:{tracking:true}}));
      }
    }""",
        dict(user=user, platform=platform, ready=ready),
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("change", ["user", "platform"])
def test_drafts_follow_account_and_platform_without_copying_private_brief(
    page, platform, change
):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = DraftNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-brief").fill("PRIVATE account A brief")
    page.locator("#intake-city").fill("PRIVATE account A city")
    page.locator("#intake-all-manager").uncheck()
    page.locator("#intake-position-7").check()
    flow_a = page.evaluate("UMCIntakeProgress.funnel()")
    user_b = (
        "22000000-0000-4000-8000-000000000099" if change == "user" else CLIENT
    )
    platform_b = (
        ("max" if platform == "telegram" else "telegram")
        if change == "platform"
        else platform
    )
    key_a = f"umc:intake-draft:{platform}:{CLIENT}"
    key_b = f"umc:intake-draft:{platform_b}:{user_b}"
    saved_a = page.evaluate("key=>sessionStorage.getItem(key)", key_a)
    switch_draft_identity(page, user_b, platform_b)
    expect(page.locator("#intake-brief")).to_have_value("")
    expect(page.locator("#intake-city")).to_have_value("")
    expect(page.locator("#intake-contact")).to_have_value("")
    expect(page.locator('input[name="intake-mode"]:checked')).to_have_value(
        "self_service"
    )
    expect(page.locator("#intake-all-manager")).to_be_checked()
    expect(page.locator("#intake-position-7")).not_to_be_checked()
    flow_b = page.evaluate("UMCIntakeProgress.funnel()")
    assert flow_b and flow_b != flow_a
    page.locator("#intake-brief").fill("PRIVATE account B brief")
    page.locator("#intake-contact").fill("PRIVATE account B contact")
    saved_b = page.evaluate("key=>sessionStorage.getItem(key)", key_b)
    assert "account A" not in saved_b
    assert page.evaluate("key=>sessionStorage.getItem(key)", key_a) == saved_a
    switch_draft_identity(page, CLIENT, platform)
    expect(page.locator("#intake-brief")).to_have_value(
        "PRIVATE account A brief"
    )
    expect(page.locator("#intake-city")).to_have_value("PRIVATE account A city")
    expect(page.locator('input[name="intake-mode"]:checked')).to_have_value(
        "with_manager"
    )
    expect(page.locator("#intake-position-7")).to_be_checked()
    assert page.evaluate("UMCIntakeProgress.funnel()") == flow_a
    switch_draft_identity(page, user_b, platform_b)
    expect(page.locator("#intake-brief")).to_have_value(
        "PRIVATE account B brief"
    )
    expect(page.locator("#intake-contact")).to_have_value(
        "PRIVATE account B contact"
    )
    assert page.evaluate("UMCIntakeProgress.funnel()") == flow_b
    assert not network.creates and not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_input_after_unannounced_switch_cannot_store_previous_brief(
    page, platform
):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = DraftNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("PRIVATE former owner brief")
    old_key = f"umc:intake-draft:{platform}:{CLIENT}"
    saved = page.evaluate("key=>sessionStorage.getItem(key)", old_key)
    user_b = "22000000-0000-4000-8000-000000000099"
    page.locator("#intake-contact").focus()
    switch_draft_identity(page, user_b, platform, ready=False)
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.insert_text("New owner contact")
    assert page.evaluate("UMCIntakeProgress.funnel()") is None
    expect(page.locator("#intake-brief")).to_have_value("")
    other = page.evaluate(
        "key=>sessionStorage.getItem(key)",
        f"umc:intake-draft:{platform}:{user_b}",
    )
    assert not other or "former owner" not in other
    assert page.evaluate("key=>sessionStorage.getItem(key)", old_key) == saved
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_stale_funnel_failure_cannot_reset_new_owner_observations(
    page, platform
):
    from tests.e2e.miniapp_helpers import generate_init_data
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = DraftNetwork()
    network.hold_opened = True
    errors = open_app(page, network, platform, init_data=SIGNED)
    with page.expect_request("**/financial/orders/funnel/stage"):
        page.locator("#btn-show-create-order").click()
    fill(page)
    flow_a = page.evaluate("UMCIntakeProgress.funnel()")
    assert len(network.held_funnels) == 1
    network.hold_opened = False
    auth_b = generate_init_data("test-token", 102, "synthetic_second_owner")
    page.evaluate("auth => {window.__host.wa.initData=auth;}", auth_b)
    with page.expect_response(
        lambda response: (
            response.url.endswith("/funnel/stage") and response.status == 200
        )
    ):
        switch_draft_identity(
            page, "22000000-0000-4000-8000-000000000099", platform
        )
    flow_b = page.evaluate("UMCIntakeProgress.funnel()")
    assert flow_a != flow_b
    with page.expect_response(
        lambda response: (
            response.url.endswith("/funnel/stage") and response.status == 503
        )
    ):
        network.held_funnels.pop().fulfill(
            status=503, json={"detail": "synthetic stale failure"}
        )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )
    page.evaluate(
        "document.dispatchEvent(new CustomEvent("
        "'umc:intake-policy-ready',{detail:{tracking:true}}))"
    )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )
    opened_a = [
        item
        for item in network.funnels
        if item["funnel_id"] == flow_a and item["stage"] == "opened"
    ]
    opened_b = [
        item
        for item in network.funnels
        if item["funnel_id"] == flow_b and item["stage"] == "opened"
    ]
    assert len(opened_a) == len(opened_b) == 1
    assert opened_a[0]["init_data"] == SIGNED
    assert opened_b[0]["init_data"] == auth_b
    assert not errors and not network.creates
    page.evaluate("auth => {window.__host.wa.initData=auth;}", SIGNED)
    switch_draft_identity(page, CLIENT, platform)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_draft_owner_switch_preserves_original_unknown_command_retry(
    page, platform
):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = DraftNetwork()
    network.abort = True
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-uncertain")).to_be_visible()
    business_key = f"umc:intake:{platform}:{CLIENT}"
    original = page.evaluate("key=>sessionStorage.getItem(key)", business_key)
    switch_draft_identity(
        page, "22000000-0000-4000-8000-000000000099", platform
    )
    assert (
        page.evaluate("key=>sessionStorage.getItem(key)", business_key)
        == original
    )
    assert len(network.creates) == 1
    switch_draft_identity(page, CLIENT, platform)
    network.abort = False
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert (
        len(network.creates) == 2 and network.creates[0] == network.creates[1]
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_variable_count_restores_high_accompaniment_ordinal_before_submit(
    page, platform
):
    network = SelectionNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-count").fill("20")
    page.locator("#intake-all-manager").uncheck()
    for ordinal in (1, 15):
        page.locator(f"#intake-position-{ordinal}").check()
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-count")).to_have_value("20")
    expect(page.locator("#intake-position-options input")).to_have_count(20)
    for ordinal in (1, 15):
        expect(page.locator(f"#intake-position-{ordinal}")).to_be_checked()
    expect(page.locator("#intake-position-2")).not_to_be_checked()
    assert network.creates == []
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert len(network.creates) == 1
    assert network.creates[0]["position_count"] == 20
    assert network.creates[0]["accompaniment_ordinals"] == [1, 15]
    assert not errors
