"""Owner payouts in actual TG/MAX templates; all host/API data is synthetic."""

from copy import deepcopy
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
ACTOR = "10000000-0000-4000-8000-000000000001"
REQ = "10000000-0000-4000-8000-000000000002"
DOC = "10000000-0000-4000-8000-000000000003"
DEST = "10000000-0000-4000-8000-000000000004"
REQUEST = "10000000-0000-4000-8000-000000000005"
REQUEST_B = "10000000-0000-4000-8000-000000000006"
HASH = "a" * 64
AT = "2026-10-24T12:00:00Z"


@pytest.fixture(autouse=True)
def short_browser_actions(page):
    page.set_default_timeout(3000)


def requirements():
    return {
        "requirements_id": REQ,
        "version": 1,
        "enabled": True,
        "readable": True,
        "effective_from": AT,
        "terms_reference": "synthetic-reference",
        "required_fields": ["recipient_name", "bank_account", "legal_status"],
        "document": {
            "document_id": DOC,
            "content_text": (
                "SYNTHETIC TEST DOCUMENT\n\n<img src=x onerror=alert(1)>"
            ),
            "source_locale": "ru",
            "sha256": HASH,
        },
        "field_definitions": [
            {
                "key": k,
                "labels": {"ru": label, "en": label},
                "help": {},
                "allowed_values": None,
            }
            for k, label in (
                ("recipient_name", "Synthetic recipient"),
                ("bank_account", "Synthetic account"),
                ("legal_status", "Published status"),
            )
        ],
    }


def mask():
    return {
        "requisites_id": DEST,
        "requirements_id": REQ,
        "requirements_version": 1,
        "document_id": DOC,
        "document_hash": HASH,
        "recorded_at": AT,
        "masked_label": "••••TEST",
        "usable": True,
        "unusable_reasons": [],
    }


def detail(state="reserved", amount="10001"):
    return {
        "request_id": REQUEST,
        "requisites_id": DEST,
        "requirements_id": REQ,
        "amount_minor": amount,
        "currency": "RUB",
        "requested_at": AT,
        "deadline_at": "2026-10-27T12:00:00Z",
        "state": state,
        "version": 1,
        "masked_label": "••••TEST",
        "block_reason": None,
        "as_of": AT,
        "current_execution": {"bank_account": "SECRET ADMIN DATA"},
        "allowed_actions": ["reveal_requisites"],
    }


class PayoutNetwork(MiniAppNetwork):
    def __init__(self, locale="ru"):
        super().__init__(
            locale if locale in ("ru", "en", "kk") else "ru", registered=True
        )
        self.locale = locale
        self.context = {
            "actor_id": ACTOR,
            "as_of": AT,
            "account_status": "active",
            "admin": True,
            "writes_paused": False,
            "financial": {
                "state": "ready",
                "currency": "RUB",
                "balances": {
                    "available_minor": "9223372036854775807",
                    "reserved_minor": "0",
                },
            },
            "requirements": requirements(),
            "masked_requisites": {
                "entries": [mask()],
                "has_more": False,
                "next_cursor": None,
            },
            "capabilities": {
                "begin_request": True,
                "store_requisites": True,
                "read_own_requests": True,
            },
            "blockers": [],
            "latest_publication": {"reason": "SECRET ADMIN DATA"},
        }
        self.rows = []
        self.pending = []
        self.hold = set()
        self.reserve_lost = False
        self.store_lost = False
        self.recorded = {"recorded": False, "observed_at": AT}
        self.preview_allowed = True
        self.errors = {}
        self.missing_country = False
        self.details = {REQUEST: detail("paid")}

    def route(self, route):  # noqa: PLR0912
        path = urlparse(route.request.url).path.removeprefix("/miniapp/api")
        if self.missing_country and path in ("/me", "/config"):
            route.fulfill(
                json=(
                    {
                        "locale": "ru",
                        "country": None,
                        "has_advertiser_profile": True,
                    }
                    if path == "/me"
                    else {
                        "countries": [
                            {"code": "ru", "name_native": "Synthetic country"}
                        ]
                    }
                )
            )
            return
        if path == "/me" and self.locale in ("be", "uz", "unknown"):
            route.fulfill(
                json={
                    "locale": self.locale,
                    "country": "ru",
                    "has_advertiser_profile": True,
                    "currency_symbol": "₽",
                }
            )
            return
        if path == "/partner/view" or path.startswith("/payouts/"):
            body = route.request.post_data_json
            self.requests.append((path, body))
            if path in self.errors:
                code, message = self.errors[path]
                route.fulfill(status=code, json={"detail": message})
                return
            if path in self.hold:
                self.pending.append((path, route, body))
                return
            if path == "/partner/view":
                route.fulfill(
                    status=503, json={"detail": "synthetic unavailable"}
                )
                return
            if path == "/payouts/read/context":
                result = self.context
            elif path == "/payouts/read/own":
                result = {
                    "entries": self.rows,
                    "has_more": False,
                    "next_cursor": None,
                    "as_of": AT,
                }
            elif path == "/payouts/read/masked":
                result = self.context["masked_requisites"]
            elif path == "/payouts/read/reserve-preview":
                result = {
                    "as_of": AT,
                    "amount_minor": body["amount_minor"],
                    "currency": "RUB",
                    "can_reserve": self.preview_allowed,
                    "blockers": []
                    if self.preview_allowed
                    else ["payout_available_insufficient"],
                }
            elif path == "/payouts/requisites":
                if self.store_lost:
                    route.abort()
                    return
                result = {
                    k: mask()[k]
                    for k in (
                        "requisites_id",
                        "requirements_id",
                        "masked_label",
                        "document_id",
                        "document_hash",
                    )
                }
            elif path == "/payouts/request":
                if self.reserve_lost:
                    route.abort()
                    return
                result = detail(amount=body["amount_minor"])
            elif path == "/payouts/operations/status":
                result = self.recorded
            elif path.startswith("/payouts/read/") and path.endswith("/detail"):
                result = self.details.get(path.split("/")[-2])
                if result is None:
                    route.fulfill(
                        status=404, json={"detail": "payout_read_not_found"}
                    )
                    return
            else:
                route.fulfill(
                    status=404, json={"detail": "payout_read_not_found"}
                )
                return
            route.fulfill(json=deepcopy(result))
            return
        super().route(route)


def enter(page, network, platform="telegram", **kwargs):
    errors = open_app(page, network, platform, **kwargs)
    if not page.locator("#screen-partner").is_visible():
        page.locator(".screen.active [data-partner-open]").click()
    page.locator("[data-payouts-open]").click()
    expect(page.locator("#payout-new")).to_be_visible()
    expect(page.locator("#payout-balance")).to_be_visible()
    return errors


def review(page, amount="100.01"):
    page.locator("#payout-new").click()
    page.locator("[data-payout-mask]").first.click()
    page.locator("#payout-amount").fill(amount)
    page.locator("#payout-preview").click()
    expect(page.locator("#payout-reserve")).to_be_enabled()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_pending_partner_does_not_block_payout_history(page, platform):
    network = PayoutNetwork()
    network.hold.add("/partner/view")
    network.rows = [detail()]
    errors = enter(page, network, platform)
    expect(page.locator("#payout-history")).to_contain_text("100,01")
    assert next(
        b for p, b in network.requests if p == "/payouts/read/context"
    ) == {
        "init_data": "synthetic-test-auth",
        "platform": platform,
        "limit": 20,
        "cursor": None,
    }
    assert (
        "SECRET ADMIN DATA" not in page.locator("#screen-payouts").inner_text()
    )
    assert not any(
        p.startswith("/payouts/read/admin/") for p, _ in network.requests
    )
    assert not errors
    for _, route, _ in network.pending:
        route.fulfill(status=503, json={"detail": "payout_unavailable"})


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_exact_preview_distinct_explicit_reserve_and_authoritative_detail(
    page, platform
):
    network = PayoutNetwork()
    enter(page, network, platform)
    review(page, "92233720368547758,07")
    assert not [p for p, _ in network.requests if p == "/payouts/request"]
    expect(page.locator("#payout-review")).to_contain_text(
        "92\u00a0233\u00a0720\u00a0368\u00a0547\u00a0758,07"
    )
    page.locator("#payout-reserve").dblclick()
    expect(page.locator("#payout-current")).to_contain_text("Выплачено")
    expect(page.locator("#payout-pending")).to_contain_text("В обработке")
    commands = [b for p, b in network.requests if p == "/payouts/request"]
    assert len(commands) == 1
    assert commands[0]["amount_minor"] == "9223372036854775807"
    assert commands[0]["currency"] == "RUB"


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unknown_reserve_reload_absent_retains_exact_explicit_retry(
    page, platform
):
    network = PayoutNetwork()
    network.reserve_lost = True
    enter(page, network, platform)
    review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    original = next(b for p, b in network.requests if p == "/payouts/request")
    page.reload()
    expect(page.locator("#screen-partner")).to_be_visible()
    page.locator("[data-payouts-open]").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    assert len([p for p, _ in network.requests if p == "/payouts/request"]) == 1
    network.context["capabilities"]["begin_request"] = False
    page.locator("#payout-refresh").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    page.locator("#payout-retry").click()
    commands = [b for p, b in network.requests if p == "/payouts/request"]
    assert commands == [original, original]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_terms_safe_text_save_acceptance_and_secret_cleanup(page, platform):
    network = PayoutNetwork()
    network.store_lost = True
    enter(page, network, platform)
    page.locator("#payout-new").click()
    page.locator("#payout-edit").click()
    expect(page.locator("#payout-document")).to_contain_text("<img")
    assert not page.locator("#payout-document img").count()
    expect(page.locator("#payout-accept")).not_to_be_checked()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE VALUE")
    page.locator("#payout-accept").check()
    page.locator("#payout-save").click()
    expect(page.locator("#payout-pending")).to_be_visible()
    assert not page.locator("[data-payout-secret]").count()
    stored = page.evaluate("JSON.stringify({...localStorage})")
    assert "SYNTHETIC PRIVATE" not in stored and "init_data" not in stored
    command = next(b for p, b in network.requests if p == "/payouts/requisites")
    assert (
        command["accepted"] is True
        and command["accepted_document_hash"] == HASH
    )
    network.recorded = {
        "recorded": True,
        "action": "StorePayoutRequisites",
        "result": {**mask(), "document_hash": "b" * 64},
    }
    page.locator("#payout-check").click()
    expect(page.locator("#payout-pending")).to_be_visible()
    assert "operation_key" in page.evaluate("JSON.stringify({...localStorage})")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_fresh_bridge_auth_fence_prevents_secret_send_and_stays_invalid(
    page, platform
):
    network = PayoutNetwork()
    enter(page, network, platform)
    page.locator("#payout-new").click()
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE VALUE")
    page.locator("#payout-accept").check()
    page.evaluate("window.__host.wa.initData = 'other-synthetic-account'")
    page.locator("#payout-save").click()
    assert not [p for p, _ in network.requests if p == "/payouts/requisites"]
    assert not page.locator("[data-payout-secret]").count()
    page.evaluate("window.__host.wa.initData = 'synthetic-test-auth'")
    expect(page.locator("#payout-error")).not_to_be_empty()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,title",
    [
        ("ru", "Выплаты"),
        ("en", "Payouts"),
        ("kk", "Төлемдер"),
        ("be", "Выплаты"),
        ("uz", "To‘lovlar"),
        ("unknown", "Выплаты"),
    ],
)
def test_locales_narrow_safe_ui(page, platform, locale, title):
    page.set_viewport_size({"width": 320, "height": 760})
    network = PayoutNetwork(locale)
    enter(page, network, platform)
    expect(page.locator("#payout-title")).to_have_text(title)
    review(page)
    page.evaluate(
        "window.__host.wa.colorScheme='dark';window.__host.events.themeChanged()"
    )
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, f"synthetic-payout-{platform}-{locale}-review-320-dark")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_final_action_and_external_departure_clear_private_controls(
    page, platform
):
    network = PayoutNetwork()
    enter(page, network, platform, native=True)
    page.locator("#payout-new").click()
    page.locator("[data-payout-mask]").first.click()
    page.locator("#payout-amount").fill("1.01")
    page.evaluate("window.__host.wa.MainButton.click()")
    expect(page.locator("#payout-reserve")).to_be_enabled()
    page.evaluate(
        "window.__host.wa.MainButton.click();window.__host.wa.MainButton.click()"
    )
    expect(page.locator("#payout-current")).to_contain_text("Выплачено")
    assert len([p for p, _ in network.requests if p == "/payouts/request"]) == 1
    page.evaluate(
        "window.__umcAppBridge.showScreen('screen-partner');window.__host.wa.MainButton.click()"
    )
    assert len([p for p, _ in network.requests if p == "/payouts/request"]) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("begin,store", [(False, True), (True, False)])
def test_capabilities_are_independent(page, platform, begin, store):
    network = PayoutNetwork()
    network.context["capabilities"].update(
        begin_request=begin, store_requisites=store
    )
    network.rows = [detail()]
    enter(page, network, platform)
    assert page.locator("#payout-new").is_enabled() is begin
    assert page.locator("#payout-edit").is_enabled() is store
    expect(page.locator("#payout-history")).to_contain_text("100,01")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("missing", ["bigint", "storage", "key"])
def test_missing_browser_capability_disables_new_mutations(
    page, platform, missing
):
    network = PayoutNetwork()
    scripts = {
        "bigint": "window.BigInt=undefined",
        "storage": (
            "Storage.prototype.getItem=()=>{"
            "throw new Error('synthetic blocked')}"
        ),
        "key": "Object.defineProperty(window,'crypto',{value:undefined})",
    }
    page.add_init_script(scripts[missing])
    enter(page, network, platform)
    expect(page.locator("#payout-new")).to_be_disabled()
    expect(page.locator("#payout-edit")).to_be_disabled()
    assert not [
        p
        for p, _ in network.requests
        if p in ("/payouts/request", "/payouts/requisites")
    ]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_preview_cannot_authorize_an_edited_amount(page, platform):
    network = PayoutNetwork()
    network.hold.add("/payouts/read/reserve-preview")
    enter(page, network, platform)
    page.locator("#payout-new").click()
    page.locator("[data-payout-mask]").first.click()
    page.locator("#payout-amount").fill("1.01")
    page.locator("#payout-preview").click()
    page.locator("#payout-amount").fill("2.02")
    _, route, _ = next(
        item for item in network.pending if item[0].endswith("reserve-preview")
    )
    route.fulfill(
        json={
            "amount_minor": "101",
            "currency": "RUB",
            "can_reserve": True,
            "blockers": [],
            "as_of": AT,
        }
    )
    expect(page.locator("#payout-preview")).to_be_enabled()
    expect(page.locator("#payout-reserve")).to_have_count(0)
    assert page.locator("#payout-amount").input_value() == "2.02"


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_conflict_refreshes_reads_and_never_replaces_unknown_intent(
    page, platform
):
    network = PayoutNetwork()
    enter(page, network, platform)
    review(page)
    network.errors["/payouts/request"] = (409, "payout_requirements_changed")
    with page.expect_request("**/payouts/read/context", timeout=3000):
        page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    expect(page.locator("#payout-live")).not_to_have_text("Загрузка…")
    assert (
        len([p for p, _ in network.requests if p == "/payouts/read/context"])
        >= 2
    )
    original = next(b for p, b in network.requests if p == "/payouts/request")
    stored = page.evaluate("JSON.stringify({...localStorage})")
    assert original["operation_key"] in stored
    assert len([p for p, _ in network.requests if p == "/payouts/request"]) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_bound_bridge_rejects_body_auth_overrides_and_permanent_identity_change(
    page, platform
):
    network = PayoutNetwork()
    open_app(page, network, platform)
    result = page.evaluate("""async () => {
      const bound=window.__umcAppBridge.createRequestContext();
      await bound.request('/payouts/read/context', {
        init_data:'wrong-synthetic',platform:'wrong',limit:20,cursor:null
      });
      const keys=Object.keys(bound).sort();
      window.__host.wa.initData='other-synthetic';
      const changed=bound.isCurrent();
      window.__host.wa.initData='synthetic-test-auth';
      let denied=false;
      try {await bound.request('/payouts/read/context',{});}
      catch(e) {denied=true;}
      return {keys,changed,denied,current:bound.isCurrent()};
    }""")
    assert result == {
        "keys": ["dispose", "isCurrent", "request"],
        "changed": False,
        "denied": True,
        "current": False,
    }
    reads = [b for p, b in network.requests if p == "/payouts/read/context"]
    assert (
        len(reads) == 1
        and reads[0]["init_data"] == "synthetic-test-auth"
        and reads[0]["platform"] == platform
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_external_departure_clears_form_and_ignores_late_store(page, platform):
    network = PayoutNetwork()
    network.hold.add("/payouts/requisites")
    enter(page, network, platform)
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE VALUE")
    page.locator("#payout-accept").check()
    page.locator("#payout-save").click()
    page.evaluate("window.__umcAppBridge.showScreen('screen-partner')")
    assert not page.locator("[data-payout-secret]").count()
    _, route, _ = next(
        item for item in network.pending if item[0].endswith("requisites")
    )
    route.fulfill(
        json={
            k: mask()[k]
            for k in (
                "requisites_id",
                "requirements_id",
                "document_id",
                "document_hash",
                "masked_label",
            )
        }
    )
    expect(page.locator("#screen-partner")).to_be_visible()
    assert "SYNTHETIC PRIVATE VALUE" not in page.evaluate(
        "document.body.textContent+JSON.stringify({...localStorage})"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_published_available_label_is_used_without_inventing_translation(
    page, platform
):
    network = PayoutNetwork()
    for field in network.context["requirements"]["field_definitions"]:
        field["labels"] = {"en": "Actual published English label"}
        field["help"] = {"en": "Actual published English help"}
    enter(page, network, platform)
    page.locator("#payout-edit").click()
    expect(page.locator('label[for="payout-field-0"]')).to_have_text(
        "Actual published English label"
    )
    expect(page.locator("#payout-field-0-help")).to_have_text(
        "Actual published English help"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_old_preview_finally_does_not_enable_a_new_pending_preview(
    page, platform
):
    network = PayoutNetwork()
    network.hold.add("/payouts/read/reserve-preview")
    enter(page, network, platform)
    page.locator("#payout-new").click()
    page.locator("[data-payout-mask]").first.click()
    page.locator("#payout-amount").fill("1.01")
    page.locator("#payout-preview").click()
    page.locator("#payout-amount").fill("2.02")
    expect(page.locator("#payout-preview")).to_be_enabled()
    page.locator("#payout-preview").click()
    _, first, _ = network.pending[0]
    first.fulfill(
        json={
            "amount_minor": "101",
            "currency": "RUB",
            "can_reserve": True,
            "as_of": AT,
            "blockers": [],
        }
    )
    expect(page.locator("#payout-preview")).to_be_disabled()
    expect(page.locator("#payout-reserve")).to_have_count(0)
    _, second, _ = network.pending[1]
    second.fulfill(
        json={
            "amount_minor": "202",
            "currency": "RUB",
            "can_reserve": True,
            "as_of": AT,
            "blockers": [],
        }
    )
    expect(page.locator("#payout-reserve")).to_be_enabled()
    expect(page.locator("#payout-review")).to_contain_text("2,02")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_delayed_reserve_receipt_a_cannot_change_pending_b(page, platform):
    network = PayoutNetwork()
    network.reserve_lost = True
    enter(page, network, platform)
    review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    network.hold.add("/payouts/operations/status")
    page.locator("#payout-check").click()
    _, delayed, _ = network.pending[0]
    network.hold.clear()
    network.recorded = {
        "recorded": True,
        "action": "RequestPayout",
        "result": detail(),
    }
    page.locator("#payout-check").click()
    page.locator("#payout-new-again").click()
    review(page, "2.02")
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    commands = [b for p, b in network.requests if p == "/payouts/request"]
    second_key = commands[-1]["operation_key"]
    assert second_key != commands[0]["operation_key"]
    delayed.fulfill(
        json={"recorded": True, "action": "RequestPayout", "result": detail()}
    )
    expect(page.locator("#payout-pending")).to_contain_text("2,02")
    expect(page.locator("#payout-new-again")).to_have_count(0)
    stored = page.evaluate("JSON.stringify({...localStorage})")
    assert second_key in stored and commands[0]["operation_key"] not in stored
    page.locator("#payout-retry").click()
    assert [b for p, b in network.requests if p == "/payouts/request"][
        -1
    ] == commands[-1]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_delayed_store_receipt_a_cannot_clear_new_private_form_b(
    page, platform
):
    network = PayoutNetwork()
    network.store_lost = True
    enter(page, network, platform)
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC INPUT A")
    page.locator("#payout-accept").check()
    page.locator("#payout-save").click()
    expect(page.locator("#payout-pending")).to_be_visible()
    network.hold.add("/payouts/operations/status")
    page.locator("#payout-check").click()
    _, delayed, _ = network.pending[0]
    network.hold.clear()
    receipt = {
        "recorded": True,
        "action": "StorePayoutRequisites",
        "result": {
            k: mask()[k]
            for k in (
                "requisites_id",
                "requirements_id",
                "document_id",
                "document_hash",
                "masked_label",
            )
        },
    }
    network.recorded = receipt
    page.locator("#payout-check").click()
    page.locator("#payout-new-again").click()
    page.locator("#payout-edit").click()
    page.locator('[name="recipient_name"]').fill("SYNTHETIC INPUT B")
    delayed.fulfill(json=receipt)
    expect(page.locator('[name="recipient_name"]')).to_have_value(
        "SYNTHETIC INPUT B"
    )
    expect(page.locator("#payout-save")).to_be_enabled()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_maximum_money_stays_on_one_line_at_320px(page, platform):
    page.set_viewport_size({"width": 320, "height": 760})
    enter(page, PayoutNetwork(), platform)
    assert page.locator("#payout-balance .umc-payout-money").evaluate("""n => {
      const r=document.createRange();r.selectNodeContents(n);
      return r.getClientRects().length===1 && n.scrollWidth<=n.clientWidth;
    }""")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "query,screen",
    [
        ("?view=payouts", "screen-payouts"),
        ("?view=payouts&view=payouts", "screen-advertiser-dashboard"),
        ("?view=payouts&view=partner", "screen-advertiser-dashboard"),
        (f"?view=payouts&selection={REQUEST}", "screen-selection"),
        (f"?view=payouts&assignment={REQUEST}", "screen-collaboration"),
        (f"?view=payouts&assignment_id={REQUEST}", "screen-collaboration"),
    ],
)
def test_payout_routing_yields_to_actual_existing_handlers(
    page, platform, query, screen
):
    network = PayoutNetwork()
    open_app(page, network, platform, query=query)
    expect(page.locator("#" + screen)).to_be_visible()
    if screen != "screen-payouts":
        assert not [p for p, _ in network.requests if p.startswith("/payouts/")]


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("code", [401, 403, 503])
def test_errors_do_not_render_untrusted_server_detail(page, platform, code):
    network = PayoutNetwork()
    network.errors["/payouts/read/context"] = (
        code,
        "SYNTHETIC PRIVATE ERROR <img src=x>",
    )
    open_app(page, network, platform)
    page.locator(".screen.active [data-partner-open]").click()
    page.locator("[data-payouts-open]").click()
    expect(page.locator("#payout-error")).not_to_be_empty()
    assert (
        "SYNTHETIC PRIVATE ERROR"
        not in page.locator("#screen-payouts").inner_text()
    )
    assert not page.locator("#screen-payouts img").count()


def test_payout_route_does_not_bypass_telegram_country_bootstrap(page):
    network = PayoutNetwork()

    network.missing_country = True
    errors = open_app(page, network, query="?view=payouts")
    expect(page.locator("#screen-country-select")).to_be_visible()
    assert not [p for p, _ in network.requests if p.startswith("/payouts/")]
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_account_switch_during_context_read_drops_foreign_completion(
    page, platform
):
    network = PayoutNetwork()
    network.hold.add("/payouts/read/context")
    open_app(page, network, platform)
    page.locator(".screen.active [data-partner-open]").click()
    page.locator("[data-payouts-open]").click()
    page.evaluate("window.__host.wa.initData='other-synthetic-account'")
    _, route, _ = next(
        item for item in network.pending if item[0].endswith("context")
    )
    route.fulfill(json=network.context)
    expect(page.locator("#payout-error")).not_to_be_empty()
    expect(page.locator("#payout-balance")).to_have_count(0)
    assert not [
        p
        for p, _ in network.requests
        if p in ("/payouts/read/own", "/payouts/read/masked")
    ]
    page.evaluate("window.__host.wa.initData='synthetic-test-auth'")
    expect(page.locator("#payout-new")).to_be_disabled()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_storage_write_failure_prevents_reserve_io(page, platform):
    network = PayoutNetwork()
    enter(page, network, platform)
    review(page)
    page.evaluate(
        "() => { Storage.prototype.setItem=()=>{"
        "throw new Error('synthetic quota')}; }"
    )
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-error")).not_to_be_empty()
    assert not [p for p, _ in network.requests if p == "/payouts/request"]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_native_back_while_store_pending_clears_private_form(page, platform):
    network = PayoutNetwork()
    network.hold.add("/payouts/requisites")
    enter(page, network, platform, native=True)
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE INPUT")
    page.locator("#payout-accept").check()
    page.evaluate("window.__host.wa.MainButton.click()")
    page.evaluate("window.__host.wa.BackButton.click()")
    expect(page.locator("#screen-partner")).to_be_visible()
    assert not page.locator("[data-payout-secret]").count()
    _, route, _ = next(
        item for item in network.pending if item[0].endswith("requisites")
    )
    route.abort()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "kind",
    [
        "wrong_action",
        "wrong_amount",
        "wrong_currency",
        "wrong_requisites",
        "missing_scope",
    ],
)
def test_mismatched_reserve_receipt_retains_uncertainty(page, platform, kind):
    network = PayoutNetwork()
    network.reserve_lost = True
    enter(page, network, platform)
    review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    receipt = {"recorded": True, "action": "RequestPayout", "result": detail()}
    if kind == "wrong_action":
        receipt["action"] = "StorePayoutRequisites"
    elif kind == "wrong_amount":
        receipt["result"]["amount_minor"] = "10002"
    elif kind == "wrong_currency":
        receipt["result"]["currency"] = "USD"
    elif kind == "wrong_requisites":
        receipt["result"]["requisites_id"] = DOC
    else:
        receipt["result"].pop("requirements_id")
    network.recorded = receipt
    page.locator("#payout-check").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    expect(page.locator("#payout-new-again")).to_have_count(0)
    original = next(b for p, b in network.requests if p == "/payouts/request")
    assert original["operation_key"] in page.evaluate(
        "JSON.stringify({...localStorage})"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "kk"])
def test_synthetic_terms_unknown_and_status_visuals(page, platform, locale):
    page.set_viewport_size({"width": 320, "height": 760})
    network = PayoutNetwork(locale)
    enter(page, network, platform)
    screenshot(page, f"synthetic-payout-{platform}-{locale}-home-320-light")
    page.locator("#payout-edit").click()
    screenshot(page, f"synthetic-payout-{platform}-{locale}-terms-320-light")
    page.locator("#payout-back").click()
    network.reserve_lost = True
    review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    page.evaluate(
        "window.__host.wa.colorScheme='dark';window.__host.events.themeChanged()"
    )
    screenshot(page, f"synthetic-payout-{platform}-{locale}-unknown-320-dark")
    network.recorded = {
        "recorded": True,
        "action": "RequestPayout",
        "result": detail(),
    }
    page.locator("#payout-check").click()
    expect(page.locator("#payout-current")).to_be_visible()
    screenshot(page, f"synthetic-payout-{platform}-{locale}-status-320-dark")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "blocker,visible",
    [
        ("payout_encryption_configuration_required", "Шифрование"),
        ("published_payout_requirements_required", "документ недоступен"),
    ],
)
def test_unavailable_action_explains_actual_context_blocker(
    page, platform, blocker, visible
):
    network = PayoutNetwork()
    network.context["blockers"] = [blocker]
    network.context["capabilities"].update(
        begin_request=False, store_requisites=False
    )
    enter(page, network, platform)
    expect(page.locator("#payout-balance")).to_contain_text(visible)
    expect(page.locator("#payout-new")).to_be_disabled()
    expect(page.locator("#payout-edit")).to_be_disabled()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_store_completion_clears_captured_form_without_touching_replaced_intent(
    page, platform
):
    network = PayoutNetwork()
    network.hold.add("/payouts/requisites")
    enter(page, network, platform)
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE A")
    page.locator("#payout-accept").check()
    page.locator("#payout-save").click()
    replacement = page.evaluate("""() => {
      const S=window.UMCPayoutState;
      const partition={platform:window.__miniapp_platform,
        actor_id:'10000000-0000-4000-8000-000000000001'};
      const a=S.read(partition).record;
      const b={version:1, action:'RequestPayout', operation_key:S.newKey(),
        requisites_id:'10000000-0000-4000-8000-000000000004',
        amount_minor:'202', currency:'RUB'};
      S.clear(partition,a);S.write(partition,b);return b.operation_key;
    }""")
    _, route, _ = next(
        item for item in network.pending if item[0].endswith("requisites")
    )
    route.fulfill(
        json={
            k: mask()[k]
            for k in (
                "requisites_id",
                "requirements_id",
                "document_id",
                "document_hash",
                "masked_label",
            )
        }
    )
    expect(page.locator("[data-payout-secret]")).to_have_count(0)
    assert replacement in page.evaluate("JSON.stringify({...localStorage})")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_identity_change_clears_owner_data_but_keeps_recovery(page, platform):
    network = PayoutNetwork()
    network.reserve_lost = True
    enter(page, network, platform)
    review(page)
    page.locator("#payout-reserve").click()
    expect(page.locator("#payout-retry")).to_be_visible()
    key = next(b for p, b in network.requests if p == "/payouts/request")[
        "operation_key"
    ]
    page.evaluate(
        "window.__host.wa.initData='other-synthetic-account';"
        "window.dispatchEvent(new Event('focus'))"
    )
    expect(page.locator("#payout-pending")).to_have_count(0)
    expect(page.locator("#payout-current")).to_have_count(0)
    expect(page.locator("#payout-balance")).to_have_count(0)
    expect(page.locator("#payout-new")).to_be_disabled()
    assert key in page.evaluate("JSON.stringify({...localStorage})")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_editing_review_requires_and_accepts_a_fresh_explicit_preview(
    page, platform
):
    network = PayoutNetwork()
    enter(page, network, platform)
    review(page)
    page.locator("#payout-amount").fill("2.02")
    expect(page.locator("#payout-reserve")).to_have_count(0)
    page.locator("#payout-preview").click()
    expect(page.locator("#payout-reserve")).to_be_enabled()
    expect(page.locator("#payout-review")).to_contain_text("2,02")
    assert not [p for p, _ in network.requests if p == "/payouts/request"]


def release_read(page, held_route, data):
    """Await the real response/body and the browser's rendering turn."""
    with page.expect_response(held_route.request.url) as response:
        held_route.fulfill(json=data)
    response.value.finished()
    page.evaluate("""() => new Promise(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    })""")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("source", ["own", "masked", "detail"])
def test_background_read_preserves_active_private_form(page, platform, source):
    network = PayoutNetwork()
    network.rows = [detail()]
    path = (
        f"/payouts/read/{REQUEST}/detail"
        if source == "detail"
        else f"/payouts/read/{source}"
    )
    network.hold.add(path)
    enter(page, network, platform)
    if source == "detail":
        page.locator("#payout-history .umc-payout-card button").first.click()
    page.locator("#payout-edit").click()
    for key in ("recipient_name", "bank_account", "legal_status"):
        page.locator(f'[name="{key}"]').fill("SYNTHETIC PRIVATE INPUT")
    page.locator("#payout-accept").check()
    form = page.locator("#payout-secret-form").element_handle()
    _, held, _ = next(item for item in network.pending if item[0] == path)
    data = (
        detail()
        if source == "detail"
        else {
            "entries": network.rows if source == "own" else [mask()],
            "has_more": False,
            "next_cursor": None,
            "as_of": AT,
        }
    )
    release_read(page, held, data)
    for key in ("recipient_name", "bank_account", "legal_status"):
        expect(page.locator(f'[name="{key}"]')).to_have_value(
            "SYNTHETIC PRIVATE INPUT"
        )
    expect(page.locator("#payout-accept")).to_be_checked()
    assert form.evaluate("n => n.isConnected")
    assert "SYNTHETIC PRIVATE INPUT" not in page.evaluate(
        "JSON.stringify({...localStorage})"
    )
    assert not [
        p
        for p, _ in network.requests
        if p in ("/payouts/request", "/payouts/requisites")
    ]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_latest_selected_detail_wins_when_older_read_finishes_last(
    page, platform
):
    network = PayoutNetwork()
    row_a = detail("reserved", "10001")
    row_b = {**detail("paid", "20202"), "request_id": REQUEST_B}
    network.rows = [row_a, row_b]
    network.details[REQUEST_B] = row_b
    path = f"/payouts/read/{REQUEST}/detail"
    network.hold.add(path)
    enter(page, network, platform)
    buttons = page.locator("#payout-history .umc-payout-card button")
    buttons.nth(0).click()
    buttons.nth(1).click()
    expect(page.locator("#payout-current")).to_contain_text("202,02")
    expect(page.locator("#payout-current")).to_contain_text("Выплачено")
    _, held, _ = next(item for item in network.pending if item[0] == path)
    release_read(page, held, row_a)
    expect(page.locator("#payout-current")).to_contain_text("202,02")
    expect(page.locator("#payout-current")).to_contain_text("Выплачено")
    assert "100,01" not in page.locator("#payout-current").inner_text()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("source", ["own", "masked", "detail"])
def test_background_read_does_not_rebuild_current_confirmation(
    page, platform, source
):
    network = PayoutNetwork()
    network.rows = [detail()]
    if source == "own":
        network.hold.add("/payouts/read/own")
    if source == "masked":
        network.context["masked_requisites"].update(
            has_more=True, next_cursor="synthetic-next-mask"
        )
    if source == "detail":
        network.hold.add(f"/payouts/read/{REQUEST}/detail")
    enter(page, network, platform)
    if source == "detail":
        page.locator("#payout-history .umc-payout-card button").first.click()
    page.locator("#payout-new").click()
    if source == "masked":
        network.hold.add("/payouts/read/masked")
        page.locator("#payout-mask-next").click()
    page.locator("[data-payout-mask]").first.click()
    page.locator("#payout-amount").fill("3.03")
    page.locator("#payout-preview").click()
    expect(page.locator("#payout-reserve")).to_be_enabled()
    confirmation = page.locator("#payout-review").element_handle()
    path, held, _ = network.pending[0]
    data = (
        detail()
        if source == "detail"
        else {
            "entries": network.rows if source == "own" else [mask()],
            "has_more": False,
            "next_cursor": None,
            "as_of": AT,
        }
    )
    assert path.endswith("/detail" if source == "detail" else source)
    release_read(page, held, data)
    assert confirmation.evaluate("n => n.isConnected")
    expect(page.locator("#payout-review")).to_contain_text("3,03")
    expect(page.locator("#payout-reserve")).to_be_enabled()
    assert not [p for p, _ in network.requests if p == "/payouts/request"]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_explicit_context_refresh_still_clears_private_form(page, platform):
    network = PayoutNetwork()
    enter(page, network, platform)
    page.locator("#payout-edit").click()
    page.locator('[name="recipient_name"]').fill("SYNTHETIC PRIVATE INPUT")
    page.locator("#payout-accept").check()
    network.context["requirements"]["document"]["sha256"] = "b" * 64
    page.locator("#payout-refresh").click()
    expect(page.locator("#payout-secret-form")).to_have_count(0)
    page.locator("#payout-edit").click()
    expect(page.locator('[name="recipient_name"]')).to_have_value("")
    expect(page.locator("#payout-accept")).not_to_be_checked()
    expect(page.locator("#screen-payouts")).to_contain_text("b" * 64)
