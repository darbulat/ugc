"""Real templates with synthetic signed API and native host boundaries."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

import pytest
from playwright.sync_api import Route, expect

from tests.e2e.miniapp_helpers import generate_init_data
from tests.e2e.test_miniapp_design_system import (
    MiniAppNetwork,
    open_app,
    screenshot,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]
CLIENT = "22000000-0000-4000-8000-000000000001"
ORDER = "22000000-0000-4000-8000-000000000002"
POLICY = "actual-synthetic-approved-v1"
SIGNED = generate_init_data("test-token", 101, "synthetic_intake")


class SelectionNetwork(MiniAppNetwork):
    def __init__(self, locale="ru", *, paused=False):
        super().__init__("ru", registered=True)
        self.locale = locale
        self.paused = paused
        self.creates = []
        self.pending = []
        self.hold = False
        self.abort = False
        self.create_code = 200
        self.selection_code = 200
        self.policies = [
            {
                "version": POLICY,
                "terms_reference": "https://example.test/actual-published-terms",
                "effective_from": "2026-10-22T00:00:00Z",
                "refund_window_seconds": 86400,
                "selection_minor": 50000,
                "accompaniment_minor": 120000,
                "position_count": 30,
                "currency": "RUB",
            }
        ]
        self.positions = [
            {
                "ordinal": 1,
                "paid_item_id": str(UUID(int=1)),
                "assignment_id": str(UUID(int=10)),
                "creator_id": str(UUID(int=11)),
                "instagram_url": "https://instagram.com/current_actual_synthetic",
                "selection_minor": 50000,
                "accompaniment_minor": 120000,
                "currency": "RUB",
                "delivery_state": "unknown",
                "delivered_at": None,
                "fulfilled_at": "2026-10-23T10:00:00Z",
                "current": True,
                "deliveries": [
                    {
                        "assignment_id": str(UUID(int=20)),
                        "creator_id": str(UUID(int=21)),
                        "instagram_url": "https://instagram.com/previous_actual_synthetic",
                        "accepted_at": "2026-10-23T10:00:00Z",
                        "current": False,
                    }
                ],
            }
        ]

    def created(self, payload):
        count = payload.get("position_count", 30)
        selected = payload.get("accompaniment_ordinals")
        if selected is None:
            selected = (
                list(range(1, count + 1))
                if payload["service_mode"] == "with_manager"
                else []
            )
        return {
            "request_id": str(UUID(int=30)),
            "order_id": ORDER,
            "requested_at": "2026-10-23T11:00:00Z",
            "currency": "RUB",
            "policy_version": POLICY,
            "selection_due_at": payload["selection_due_at"],
            "terms_reference": self.policies[0]["terms_reference"],
            "items": [
                {
                    "paid_item_id": str(UUID(int=n)),
                    "ordinal": n,
                    "selection_minor": 50000,
                    "accompaniment_minor": 120000 if n in selected else 0,
                }
                for n in range(1, count + 1)
            ],
            "lead_id": str(UUID(int=31)) if selected else None,
            "honorarium_payment": "paid_direct",
            "total_minor": 50000 * count + 120000 * len(selected),
            "selection_base_minor": 50000 * count,
        }

    def route(self, route: Route):
        path = urlparse(route.request.url).path
        if path == "/miniapp/api/me":
            route.fulfill(
                json={
                    "user_id": CLIENT,
                    "locale": self.locale,
                    "country": "ru",
                    "currency_code": "RUB",
                    "currency_symbol": "₽",
                    "has_advertiser_profile": self.registered,
                    "has_blogger_profile": False,
                    "is_manager": False,
                }
            )
            return
        if path.endswith("/checkout-status"):
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                json={
                    "order_id": path.split("/")[-2],
                    "invoice_state": "not_requested",
                    "capture_state": "not_recorded",
                    "writes_paused": True,
                    "can_open": False,
                }
            )
            return
        if path == "/miniapp/api/financial/orders/policies":
            self.requests.append((path, route.request.post_data_json))
            route.fulfill(
                json={
                    "writes_paused": self.paused,
                    "currency": "RUB",
                    "policies": [] if self.paused else self.policies,
                }
            )
            return
        if path == "/miniapp/api/financial/orders":
            payload = route.request.post_data_json
            self.creates.append(payload)
            if self.abort:
                route.abort("failed")
            elif self.create_code != 200:
                route.fulfill(
                    status=self.create_code,
                    json={"detail": "synthetic rejected retry"},
                )
            elif self.hold:
                self.pending.append((route, payload))
            else:
                route.fulfill(json=self.created(payload))
            return
        if path == f"/miniapp/api/financial/orders/{ORDER}/selection":
            self.requests.append((path, route.request.post_data_json))
            if self.selection_code != 200:
                route.fulfill(
                    status=self.selection_code,
                    json={"detail": "synthetic selection unavailable"},
                )
                return
            route.fulfill(
                json={
                    "order_id": ORDER,
                    "policy_version": POLICY,
                    "positions": self.positions,
                    "waitlist_count": 3,
                    "writes_paused": self.paused,
                }
            )
            return
        super().route(route)


def fill(page, *, manager=False):
    page.locator("#intake-count").fill("30")
    page.locator("#intake-policy").select_option(POLICY)
    page.locator("#intake-product").fill("https://example.test/real-product")
    page.locator("#intake-brief").fill("Actual synthetic requested brief")
    page.locator("#intake-honorarium").fill("999.00")
    page.locator("#intake-contact").fill("@actual_synthetic_client")
    due = datetime.now(timezone.utc) + timedelta(days=3)
    page.locator("#intake-due").fill(due.strftime("%Y-%m-%dT%H:%M"))
    if manager:
        page.locator('input[name="intake-mode"][value="with_manager"]').check()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_actual_intake_uses_server_policy_and_persisted_quote(
    page, platform, locale
):
    network = SelectionNetwork(locale)
    errors = open_app(page, network, platform, init_data=SIGNED)
    expect(page.locator("#btn-show-create-order")).to_be_visible()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#screen-intake")).to_be_visible()
    fill(page, manager=True)
    expect(page.locator("#btn-intake-create")).to_have_text(
        {
            "ru": "Перейти к оплате",
            "en": "Continue to payment",
            "kk": "Төлемге өту",
            "be": "Перайсці да аплаты",
            "uz": "To‘lovga o‘tish",
        }[locale]
    )
    page.locator("#intake-all-manager").uncheck()
    page.locator("#intake-position-1").check()
    page.locator("#intake-position-7").check()
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    expect(page.locator("#btn-intake-new")).to_have_text(
        {
            "ru": "Создать ещё один заказ",
            "en": "Create another order",
            "kk": "Тағы бір тапсырыс жасау",
            "be": "Стварыць яшчэ адзін заказ",
            "uz": "Yana buyurtma yaratish",
        }[locale]
    )
    expect(page.locator("#intake-total")).to_have_attribute(
        "data-minor", "1740000"
    )
    assert (
        page.locator(
            '#intake-components [data-position-total="170000"]'
        ).count()
        == 2
    )
    assert len(network.creates) == 1
    sent = network.creates[0]
    assert sent["init_data"] == SIGNED and sent["platform"] == platform
    assert sent["policy_version"] == POLICY
    assert sent["accompaniment_ordinals"] == [1, 7]
    assert sent["honorarium"] == "999.00"
    assert (
        not {
            "client_id",
            "order_id",
            "manager_id",
            "approved_at",
            "amount_minor",
        }
        & sent.keys()
    )
    assert page.locator('#screen-intake [href*="pay"]').count() == 0
    assert errors == []


def test_uncertain_create_keeps_same_payload_and_key_until_explicit_retry(page):
    network = SelectionNetwork()
    network.abort = True
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    expect(page.locator("#btn-intake-new")).to_be_hidden()
    assert len(network.creates) == 1
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    expect(page.locator("#btn-intake-new")).to_be_hidden()
    assert len(network.creates) == 1
    network.abort = False
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0] == network.creates[1]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_completed_receipt_allows_explicit_new_order_with_fresh_key(
    page, platform
):
    network = SelectionNetwork("en")
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-all-manager").uncheck()
    page.locator("#intake-position-7").check()
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    expect(page.locator("#btn-intake-new")).to_have_text("Create another order")
    page.locator("#btn-intake-new").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    expect(page.locator("#intake-result")).to_be_hidden()
    expect(page.locator("#intake-product")).to_have_value("")
    expect(page.locator("#intake-brief")).to_have_value("")
    expect(page.locator("#intake-policy")).to_have_value(POLICY)
    expect(
        page.locator('input[name="intake-mode"][value="self_service"]')
    ).to_be_checked()
    expect(page.locator("#intake-all-manager")).to_be_checked()
    assert page.locator("#intake-position-options input:checked").count() == 0
    assert page.evaluate("sessionStorage.length") == 0
    assert len(network.creates) == 1
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert len(network.creates) == 2
    assert (
        network.creates[0]["operation_key"]
        != network.creates[1]["operation_key"]
    )
    assert network.creates[1]["service_mode"] == "self_service"
    assert network.creates[1]["accompaniment_ordinals"] == []
    assert errors == []


def test_completed_receipt_reset_requires_safe_pending_storage_cleanup(page):
    network = SelectionNetwork("en")
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    page.evaluate(
        "payload => sessionStorage.setItem("
        "'umc:intake:telegram:' + payload.client, "
        "JSON.stringify(payload.request))",
        {"client": CLIENT, "request": network.creates[0]},
    )
    page.evaluate("""() => {
        window.syntheticRemoveItem = Storage.prototype.removeItem;
        Storage.prototype.removeItem = () => {
            throw new Error('synthetic storage failure');
        };
    }""")
    page.locator("#btn-intake-new").click()
    expect(page.locator("#intake-error")).to_contain_text("safe retry")
    expect(page.locator("#intake-result")).to_be_visible()
    expect(page.locator("#form-umc-intake")).to_be_hidden()
    assert page.evaluate("sessionStorage.length") == 1
    assert len(network.creates) == 1
    page.evaluate(
        "() => { Storage.prototype.removeItem = window.syntheticRemoveItem; }"
    )
    page.locator("#btn-intake-new").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    assert page.evaluate("sessionStorage.length") == 0
    assert len(network.creates) == 1


def test_rejected_retry_cannot_discard_previously_unknown_original_request(
    page,
):
    network = SelectionNetwork()
    network.abort = True
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    network.abort = False
    network.create_code = 422
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-error")).not_to_be_empty()
    expect(page.locator("#screen-intake")).to_have_attribute(
        "aria-busy", "false"
    )
    expect(page.locator("#btn-intake-retry")).to_be_visible()
    expect(page.locator("#form-umc-intake")).to_be_hidden()
    network.create_code = 200
    page.locator("#btn-intake-retry").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0] == network.creates[1] == network.creates[2]


@pytest.mark.parametrize("locale", ["ru", "en", "kk", "be", "uz"])
def test_paused_intake_is_localized_readable_at_320px(page, locale):
    page.set_viewport_size({"width": 320, "height": 720})
    network = SelectionNetwork(locale, paused=True)
    errors = open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-paused")).to_be_visible()
    expect(page.locator("#form-umc-intake")).to_be_hidden()
    assert network.creates == []
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, f"intake-{locale}-paused-320")
    assert errors == []


def test_selection_replacement_never_claims_new_creator_delivered(page):
    network = SelectionNetwork(paused=True)
    errors = open_app(
        page, network, init_data=SIGNED, query=f"?selection={ORDER}"
    )
    expect(page.locator("#screen-selection")).to_be_visible()
    expect(
        page.locator('[data-position="1"] [data-current-delivery]')
    ).to_have_attribute("data-state", "unknown")
    expect(
        page.locator('[data-position="1"] [data-delivery-history]')
    ).to_contain_text("previous_actual_synthetic")
    expect(page.locator("#selection-paused")).to_be_visible()
    assert [
        body for path, body in network.requests if path.endswith("/selection")
    ][-1] == {
        "init_data": SIGNED,
        "platform": "telegram",
    }
    assert (
        page.locator("#screen-selection [data-provider-command]").count() == 0
    )
    assert errors == []


def test_accepted_projection_without_current_immutable_receipt_stays_unknown(
    page,
):
    network = SelectionNetwork()
    network.positions[0]["delivery_state"] = "accepted"
    open_app(page, network, init_data=SIGNED, query=f"?selection={ORDER}")
    expect(page.locator("#screen-selection")).to_be_visible()
    expect(
        page.locator('[data-position="1"] [data-current-delivery]')
    ).to_have_attribute("data-state", "unknown")


def test_v1_list_links_to_actual_selection_without_legacy_pay_control(page):
    network = SelectionNetwork()
    network.order = {
        "order_id": ORDER,
        "status": "new",
        "product_link": "https://example.test/product",
        "price": 999,
        "currency_symbol": "₽",
        "created_at": "2026-10-23T10:00:00Z",
        "financial_version": POLICY,
        "payment_link": "https://t.me/synthetic?start=pay_fake",
    }
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-orders-list").click()
    expect(page.locator("#screen-customer-orders article")).to_be_visible()
    assert page.locator('#orders-list a[href*="pay_"]').count() == 0
    page.locator("#screen-customer-orders article button").first.click()
    expect(page.locator("#screen-selection")).to_be_visible()


def test_pending_native_action_cannot_double_send_and_back_is_real(page):
    network = SelectionNetwork()
    network.hold = True
    try:
        open_app(page, network, native=True, init_data=SIGNED)
        page.wait_for_function("window.__host.wa.MainButton.visible")
        page.evaluate("window.__host.wa.MainButton.click()")
        fill(page)
        page.wait_for_function(
            "window.__host.wa.MainButton.visible && "
            "window.__host.wa.MainButton.params.is_active"
        )
        page.evaluate("window.__host.wa.MainButton.click()")
        expect(page.locator("#screen-intake")).to_have_attribute(
            "aria-busy", "true"
        )
        page.evaluate("window.__host.wa.MainButton.click()")
        expect(page.locator("#intake-result")).to_be_hidden()
        assert len(network.creates) == len(network.pending) == 1
        route, payload = network.pending.pop()
        route.fulfill(json=network.created(payload))
        expect(page.locator("#intake-result")).to_be_visible()
        page.evaluate("window.__host.wa.BackButton.click()")
        expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    finally:
        for route, payload in network.pending:
            route.fulfill(json=network.created(payload))


def test_no_eligible_policy_never_shows_action_or_guesses_a_version(page):
    network = SelectionNetwork()
    network.policies = []
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-empty")).to_be_visible()
    expect(page.locator("#form-umc-intake")).to_be_hidden()
    assert network.creates == []


def test_opaque_published_terms_reference_remains_visible_literal_text(page):
    network = SelectionNetwork()
    reference = "actual-published-reference:<b>terms</b>"
    network.policies[0]["terms_reference"] = reference
    open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    page.locator("#intake-policy").select_option(POLICY)
    expect(page.locator("#intake-terms")).to_contain_text(reference)
    assert page.locator("#intake-terms b").count() == 0


@pytest.mark.parametrize("status", [403, 404, 503])
def test_unavailable_selection_clears_previously_visible_private_facts(
    page, status
):
    network = SelectionNetwork()
    open_app(page, network, init_data=SIGNED, query=f"?selection={ORDER}")
    expect(page.locator('[data-position="1"]')).to_be_visible()
    network.selection_code = status
    page.locator("#btn-selection-refresh").click()
    expect(page.locator("#selection-error")).not_to_be_empty()
    assert page.locator("[data-position]").count() == 0
    if status == 503:
        expect(page.locator("#selection-error")).to_contain_text(
            "Не удалось загрузить данные"
        )


@pytest.mark.parametrize(
    "query",
    [
        "?selection=invalid",
        f"?selection={ORDER}&selection={ORDER}",
        "?selection=00000000-0000-0000-0000-000000000000",
    ],
)
def test_invalid_selection_context_never_fetches_private_order(page, query):
    network = SelectionNetwork()
    open_app(page, network, init_data=SIGNED, query=query)
    expect(page.locator("#selection-error")).not_to_be_empty()
    assert not [
        path for path, _ in network.requests if path.endswith("/selection")
    ]


def test_source_text_is_safe_and_current_acceptance_needs_matching_fact(page):
    network = SelectionNetwork()
    position = network.positions[0]
    position["delivery_state"] = "accepted"
    position["delivered_at"] = "2026-10-23T11:00:00Z"
    position["instagram_url"] = "javascript:window.injected=true"
    position["deliveries"].append(
        {
            "assignment_id": position["assignment_id"],
            "creator_id": position["creator_id"],
            "instagram_url": "<img src=x onerror=window.injected=true>",
            "accepted_at": position["delivered_at"],
            "current": True,
        }
    )
    errors = open_app(
        page, network, init_data=SIGNED, query=f"?selection={ORDER}"
    )
    expect(page.locator("[data-current-delivery]")).to_have_attribute(
        "data-state", "accepted"
    )
    expect(page.locator("[data-delivery-history]")).to_contain_text(
        "<img src=x"
    )
    assert page.locator("#screen-selection img").count() == 0
    assert page.locator('#screen-selection a[href^="javascript:"]').count() == 0
    assert page.evaluate("window.injected === undefined")
    assert errors == []


@pytest.mark.parametrize("platform,locale", [("telegram", "ru"), ("max", "kk")])
def test_dark_form_quote_and_selection_fit_320px(page, platform, locale):
    page.set_viewport_size({"width": 320, "height": 720})
    network = SelectionNetwork(locale)
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.evaluate(
        "window.__host.wa.colorScheme='dark'; "
        "window.__host.events.themeChanged()"
    )
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator("#intake-terms")).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, f"intake-{platform}-{locale}-form-dark-320")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-total")).to_have_attribute(
        "data-minor", "5100000"
    )
    expect(page.locator("#intake-lead-state")).to_have_attribute(
        "data-state", "requested_unpaid"
    )
    screenshot(page, f"intake-{platform}-{locale}-saved-dark-320")
    page.locator("#btn-intake-selection").click()
    expect(page.locator("[data-current-delivery]")).to_have_attribute(
        "data-state", "unknown"
    )
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, f"selection-{platform}-{locale}-history-dark-320")
    assert errors == []


def test_light_320px_subset_grid_supports_keyboard_and_exact_quote(page):
    page.set_viewport_size({"width": 320, "height": 720})
    network = SelectionNetwork("en")
    errors = open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-all-manager").uncheck()
    page.locator("#intake-position-1").focus()
    page.keyboard.press("Space")
    page.locator("#intake-position-30").check()
    expect(page.locator("#intake-position-1")).to_be_checked()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    screenshot(page, "intake-en-subset-light-320")
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-total")).to_have_attribute(
        "data-minor", "1740000"
    )
    screenshot(page, "intake-en-subset-saved-light-320")
    assert errors == []
