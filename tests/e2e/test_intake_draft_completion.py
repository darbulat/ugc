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


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_draft_survives_closing_and_reopening_webview(page, platform):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-brief").fill("Saved brief after reopening")
    page.locator("#intake-all-manager").uncheck()
    page.locator("#intake-position-7").check()
    context = page.context
    page.close()

    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#intake-brief")).to_have_value(
            "Saved brief after reopening"
        )
        expect(reopened.locator("#intake-position-7")).to_be_checked()
        assert network.creates == []
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_legacy_session_draft_is_migrated_before_webview_closes(page, platform):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Legacy draft before upgrade")
    page.evaluate("() => UMCIntakeProgress.flush()")
    key = f"umc:intake-draft:{platform}:{CLIENT}"
    page.evaluate(
        """async key => {
      const data = JSON.parse(sessionStorage.getItem(key));
      for (const name of Object.keys(localStorage))
        if (name.startsWith(key + ':v:')) localStorage.removeItem(name);
      await new Promise((resolve, reject) => {
        const request = indexedDB.deleteDatabase('umc-intake-recovery');
        request.onsuccess = resolve;
        request.onerror = () => reject(request.error);
      });
      sessionStorage.setItem(key,
        JSON.stringify({values:data.values, flow:data.flow}));
    }""",
        key,
    )
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-brief")).to_have_value(
        "Legacy draft before upgrade"
    )
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#intake-brief")).to_have_value(
            "Legacy draft before upgrade"
        )
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_two_legacy_windows_cannot_submit_the_same_draft_twice(page, platform):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Shared legacy draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    key = f"umc:intake-draft:{platform}:{CLIENT}"
    legacy = page.evaluate(
        """key => {
      const data=JSON.parse(sessionStorage.getItem(key));
      return JSON.stringify({values:data.values,flow:data.flow});
    }""",
        key,
    )
    other = page.context.new_page()
    try:
        open_app(other, network, platform, init_data=SIGNED)
        other.wait_for_function("window.__umcAppReady === true")
        other.evaluate("() => UMCIntakeProgress.prepare()")
        other.evaluate(
            "data => sessionStorage.setItem(data.key, data.legacy)",
            {"key": key, "legacy": legacy},
        )
        page.evaluate(
            """async data => {
          for (const name of Object.keys(localStorage))
            if (name.startsWith(data.key + ':v:'))
              localStorage.removeItem(name);
          await new Promise((resolve, reject) => {
            const req=indexedDB.deleteDatabase('umc-intake-recovery');
            req.onsuccess=resolve; req.onerror=() => reject(req.error);
          });
          sessionStorage.setItem(data.key, data.legacy);
        }""",
            {"key": key, "legacy": legacy},
        )
        page.reload()
        page.locator("#btn-show-create-order").click()
        expect(page.locator("#intake-brief")).to_have_value(
            "Shared legacy draft"
        )
        other.reload()
        other.locator("#btn-show-create-order").click()
        expect(other.locator("#intake-brief")).to_have_value(
            "Shared legacy draft"
        )
        first_group = page.evaluate(
            "JSON.parse(UMCIntakeProgress.snapshot()).draft_group"
        )
        second_group = other.evaluate(
            "JSON.parse(UMCIntakeProgress.snapshot()).draft_group"
        )
        assert first_group == second_group == "0" * 32
        page.locator("#btn-intake-create").click()
        expect(page.locator("#intake-result")).to_be_visible()
        page.locator("#btn-intake-new").click()
        expect(page.locator("#form-umc-intake")).to_be_visible()
        other.locator("#btn-intake-create").click()
        expect(other.locator("#intake-error")).not_to_be_empty()
        expect(other.locator("#btn-intake-fresh")).to_be_visible()
        assert len(network.creates) == 1
    finally:
        other.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_legacy_request_cannot_resubmit_its_restored_draft(page, platform):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Previously sent legacy draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    key = f"umc:intake-draft:{platform}:{CLIENT}"
    pending_key = f"umc:intake:{platform}:{CLIENT}"
    page.evaluate(
        """async data => {
      const field = id => document.getElementById(id).value;
      const saved=JSON.parse(sessionStorage.getItem(data.key));
      const request={
        operation_key:'miniapp:intake:previous-legacy-command',
        policy_version:field('intake-policy'),
        product_link:field('intake-product').trim(),
        offer_text:field('intake-brief').trim(),
        honorarium:Number(field('intake-honorarium')).toFixed(2),
        selection_due_at:new Date(field('intake-due')).toISOString(),
        contact_reference:field('intake-contact').trim(),
        position_count:Number(field('intake-count')),
        service_mode:'self_service',accompaniment_ordinals:[],
        order_type:field('intake-order-type')
      };
      for (const name of Object.keys(localStorage))
        if (name.startsWith(data.key + ':v:')) localStorage.removeItem(name);
      await new Promise((resolve, reject) => {
        const req=indexedDB.deleteDatabase('umc-intake-recovery');
        req.onsuccess=resolve; req.onerror=() => reject(req.error);
      });
      sessionStorage.setItem(data.key,
        JSON.stringify({values:saved.values,flow:saved.flow}));
      sessionStorage.setItem(data.pending,JSON.stringify(request));
    }""",
        {"key": key, "pending": pending_key},
    )
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-result")).to_be_visible()
    page.locator("#btn-intake-new").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#intake-brief")).to_have_value(
            "Previously sent legacy draft"
        )
        reopened.locator("#btn-intake-create").click()
        expect(reopened.locator("#btn-intake-fresh")).to_be_visible()
        assert len(network.creates) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_legacy_draft_reports_session_only_when_durable_storage_fails(
    page, platform
):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Legacy session draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    key = f"umc:intake-draft:{platform}:{CLIENT}"
    page.evaluate(
        """async key => {
      const data = JSON.parse(sessionStorage.getItem(key));
      for (const name of Object.keys(localStorage))
        if (name.startsWith(key + ':v:')) localStorage.removeItem(name);
      await new Promise((resolve, reject) => {
        const request = indexedDB.deleteDatabase('umc-intake-recovery');
        request.onsuccess = resolve;
        request.onerror = () => reject(request.error);
      });
      sessionStorage.setItem(key,
        JSON.stringify({values:data.values, flow:data.flow}));
    }""",
        key,
    )
    page.add_init_script(
        script="""(() => {
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (this === localStorage && key.startsWith('umc:intake-draft:'))
          throw new Error('synthetic local storage failure');
        return set.call(this, key, value);
      };
      const put = IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put = function(...args) {
        if (this.name === 'drafts')
          throw new Error('synthetic database failure');
        return put.apply(this, args);
      };
    })();"""
    )
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-brief")).to_have_value("Legacy session draft")
    expect(page.locator("#form-umc-intake [role=status]")).to_contain_text(
        "в этой сессии"
    )
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#intake-brief")).to_have_value("")
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_newer_indexeddb_draft_wins_after_local_storage_fails(page, platform):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Older local draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    page.evaluate("""() => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (this === localStorage && key.startsWith('umc:intake-draft:'))
          throw new Error('synthetic local storage failure');
        return original.call(this, key, value);
      };
    }""")
    page.locator("#intake-brief").fill("Newer IndexedDB draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#intake-brief")).to_have_value(
            "Newer IndexedDB draft"
        )
        reopened.locator("#btn-intake-create").click()
        expect(reopened.locator("#intake-result")).to_be_visible()
        reopened.close()
        after_order = context.new_page()
        try:
            open_app(after_order, network, platform, init_data=SIGNED)
            after_order.locator("#btn-show-create-order").click()
            expect(after_order.locator("#btn-intake-retry")).to_be_visible()
            after_order.locator("#btn-intake-retry").click()
            expect(after_order.locator("#intake-result")).to_be_visible()
            after_order.locator("#btn-intake-new").click()
            expect(after_order.locator("#form-umc-intake")).to_be_visible()
            expect(after_order.locator("#intake-brief")).to_have_value("")
        finally:
            after_order.close()
    finally:
        if not reopened.is_closed():
            reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_completed_local_draft_clears_older_indexeddb_copy(page, platform):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Older IndexedDB draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    page.evaluate("""() => {
      window.originalDraftWrite = UMCIntakeStore.writeDraft;
      UMCIntakeStore.writeDraft = () => Promise.reject(new Error('synthetic'));
    }""")
    page.locator("#intake-brief").fill("Newer local draft")
    page.evaluate("() => UMCIntakeProgress.flush()")
    page.evaluate(
        "() => { UMCIntakeStore.writeDraft = window.originalDraftWrite; }"
    )
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#btn-intake-retry")).to_be_visible()
        reopened.locator("#btn-intake-retry").click()
        expect(reopened.locator("#intake-result")).to_be_visible()
        reopened.locator("#btn-intake-new").click()
        expect(reopened.locator("#form-umc-intake")).to_be_visible()
        expect(reopened.locator("#intake-brief")).to_have_value("")
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_draft_write_cannot_replace_newer_other_window(page, platform):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    block_local_drafts = """() => {
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (this === localStorage && key.startsWith('umc:intake-draft:'))
          throw new Error('synthetic local storage failure');
        return original.call(this, key, value);
      };
    }"""
    page.evaluate(block_local_drafts)
    page.evaluate("""() => {
      const original = UMCIntakeStore.writeDraft;
      UMCIntakeStore.writeDraft = (owner, raw) =>
        new Promise((resolve, reject) => {
        window.releaseDraftWrite = () => {
          UMCIntakeStore.writeDraft = original;
          original(owner, raw).then(resolve, reject);
        };
      });
    }""")
    fill(page)
    page.locator("#intake-brief").fill("Older first window draft")
    page.wait_for_function("typeof window.releaseDraftWrite === 'function'")
    other = page.context.new_page()
    try:
        open_app(other, network, platform, init_data=SIGNED)
        other.locator("#btn-show-create-order").click()
        other.evaluate(block_local_drafts)
        fill(other)
        other.locator("#intake-brief").fill("Newer second window draft")
        other.evaluate("() => UMCIntakeProgress.flush()")
        page.evaluate(
            "() => { window.releaseDraftWrite(); "
            "return UMCIntakeProgress.flush(); }"
        )
        context = page.context
        other.close()
        page.close()
        reopened = context.new_page()
        try:
            open_app(reopened, network, platform, init_data=SIGNED)
            reopened.locator("#btn-show-create-order").click()
            expect(reopened.locator("#intake-brief")).to_have_value(
                "Newer second window draft"
            )
        finally:
            reopened.close()
    finally:
        if not other.is_closed():
            other.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_confirmed_order_does_not_restore_its_old_draft(page, platform):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("Already submitted brief")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    context = page.context
    page.close()
    reopened = context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        reopened.locator("#btn-show-create-order").click()
        expect(reopened.locator("#btn-intake-retry")).to_be_visible()
        assert len(network.creates) == 1
        reopened.locator("#btn-intake-retry").click()
        expect(reopened.locator("#intake-result")).to_be_visible()
        reopened.locator("#btn-intake-new").click()
        expect(reopened.locator("#form-umc-intake")).to_be_visible()
        expect(reopened.locator("#intake-brief")).to_have_value("")
        assert network.creates[0] == network.creates[1]
    finally:
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_confirming_order_does_not_erase_another_windows_newer_draft(
    page, platform
):
    network = SelectionNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("First window order")
    other = page.context.new_page()
    try:
        open_app(other, network, platform, init_data=SIGNED)
        other.locator("#btn-show-create-order").click()
        other.locator("#intake-brief").fill("Second window draft")
        page.locator("#btn-intake-create").click()
        expect(page.locator("#intake-result")).to_be_visible()
        page.locator("#btn-intake-new").click()
        expect(page.locator("#form-umc-intake")).to_be_visible()
        context = page.context
        other.close()
        page.close()
        reopened = context.new_page()
        try:
            open_app(reopened, network, platform, init_data=SIGNED)
            reopened.locator("#btn-show-create-order").click()
            expect(reopened.locator("#form-umc-intake")).to_be_visible()
            expect(reopened.locator("#intake-brief")).to_have_value(
                "Second window draft"
            )
            assert len(network.creates) == 1
        finally:
            reopened.close()
    finally:
        if not other.is_closed():
            other.close()


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
def test_persistent_pending_and_draft_do_not_cross_accounts(page, platform):
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    network = DraftNetwork()
    network.abort = True
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("PRIVATE original account request")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    other = page.context.new_page()
    try:
        open_app(other, network, platform, init_data=SIGNED)
        switch_draft_identity(
            other, "22000000-0000-4000-8000-000000000099", platform
        )
        other.locator("#btn-show-create-order").click()
        expect(other.locator("#form-umc-intake")).to_be_visible()
        expect(other.locator("#intake-brief")).to_have_value("")
        expect(other.locator("#btn-intake-retry")).to_be_hidden()
        assert len(network.creates) == 1
        switch_draft_identity(other, CLIENT, platform)
        expect(other.locator("#btn-intake-retry")).to_be_visible()
        assert len(network.creates) == 1
    finally:
        other.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_stale_me_response_cannot_unlock_previous_accounts_pending_order(
    page, platform
):
    from urllib.parse import urlparse

    from tests.e2e.miniapp_helpers import generate_init_data
    from tests.e2e.test_miniapp_selection_ui import CLIENT

    class HeldMeNetwork(DraftNetwork):
        def __init__(self):
            super().__init__()
            self.hold_me = False
            self.held_me = []

        def route(self, route):
            if self.hold_me and urlparse(route.request.url).path.endswith(
                "/me"
            ):
                self.held_me.append(route)
            else:
                super().route(route)

    network = HeldMeNetwork()
    network.abort = True
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("PRIVATE original account request")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    network.hold_me = True
    reopened = page.context.new_page()
    try:
        open_app(reopened, network, platform, init_data=SIGNED)
        for _ in range(100):
            if network.held_me:
                break
            reopened.wait_for_timeout(25)
        assert len(network.held_me) == 1
        auth_b = generate_init_data("test-token", 102, "synthetic_second_owner")
        reopened.evaluate("auth => { window.__host.wa.initData=auth; }", auth_b)
        network.held_me.pop().fulfill(
            json={
                "user_id": CLIENT,
                "locale": "ru",
                "country": "ru",
                "currency_code": "RUB",
                "currency_symbol": "₽",
                "has_advertiser_profile": True,
                "has_blogger_profile": False,
                "is_manager": False,
            }
        )
        expect(reopened.locator("#screen-loading")).to_have_attribute(
            "data-failed", "true"
        )
        assert not reopened.evaluate("window.__umcAppReady === true")
        assert len(network.creates) == 1
    finally:
        for route in network.held_me:
            route.abort()
        reopened.close()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_new_credentials_cannot_retry_previous_accounts_pending_order(
    page, platform
):
    from tests.e2e.miniapp_helpers import generate_init_data

    network = DraftNetwork()
    network.abort = True
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill("PRIVATE original account request")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    auth_b = generate_init_data("test-token", 102, "synthetic_second_owner")
    page.evaluate("auth => { window.__host.wa.initData=auth; }", auth_b)
    network.abort = False
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-error")).not_to_be_empty()
    assert len(network.creates) == 1


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
